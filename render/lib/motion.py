"""单帧运动合成 (Motion Synthesis) —— 让静帧真的"动"，而不是被推拉。

为什么需要它
    2.5D 视差只是把整张图平移/缩放，画面内部零运动 → 观感就是 PPT。
    真正的"动作感"来自画面内部的连续形变（衣袂、雾、能量、身体位移）。

提供三件事
    1. velocity_field()  按镜头参数生成平滑速度场（可叠加旋涡/径向/上浮）
    2. warp()            双线性反向采样，把图像沿速度场形变（可带湿边/边界保护）
    3. shutter()         N 个子帧累积，沿速度方向做真实的运动模糊

全部 numpy 实现，无 GPU、无 cv2 依赖。
"""
import numpy as np


# ---------------------------------------------------------------- 速度场
def velocity_field(w, h, *, direction=(0.0, -1.0), swirl=0.0, radial=0.0, rise=0.0,
                   center=(0.5, 0.5), falloff=1.0, noise=None, noise_amp=0.0, scale=1.0):
    """构造平滑速度场，返回 (h,w,2) float32（单位：像素/秒）。

    direction : 主方向（风速方向），会被 swirl/radial 调制
    swirl     : 绕 center 的旋转强度（正=逆时针）
    radial    : 从 center 向外/向内的径向强度（负=向内收缩）
    rise      : 向上浮的强度（火焰、烬、上升气流）
    falloff   : 距中心衰减指数（1=线性，2=更集中于中心）
    noise     : (Hn,Wn) 低频噪声，用来让场"有机"而不是机器感
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx / w - center[0]) * 2.0
    ny = (yy / h - center[1]) * 2.0
    r = np.sqrt(nx ** 2 + ny ** 2) + 1e-6
    # 衰减：中心强、边缘弱
    f = 1.0 / (1.0 + (r / max(1e-3, falloff)) ** 2)
    # 归一化后做大小尺度
    sc = max(w, h) / 720.0 * scale

    dx = np.full((h, w), direction[0], np.float32) * f
    dy = np.full((h, w), direction[1], np.float32) * f

    if swirl:
        tx, ty = -ny / r, nx / r          # 切向
        dx += tx * swirl * f
        dy += ty * swirl * f
    if radial:
        dx += (nx / r) * radial * f
        dy += (ny / r) * radial * f
    if rise:
        dy -= rise * (yy / h) ** 0.6      # 越靠下越往上浮

    if noise is not None and noise_amp:
        n = noise
        gx = np.gradient(n, axis=1)
        gy = np.gradient(n, axis=0)
        s = max(h, w) / n.shape[0]
        gx = np.asarray(_resize_np(gx, (h, w))) * s
        gy = np.asarray(_resize_np(gy, (h, w))) * s
        dx += gx * noise_amp
        dy += gy * noise_amp

    v = np.stack([dx, dy], -1).astype(np.float32) * sc
    return v


def _resize_np(a, shape):
    """numpy 双线性缩放（避免依赖 PIL，保持无状态）。"""
    h, w = shape
    H, W = a.shape
    yi = np.linspace(0, H - 1, h).astype(np.float32)
    xi = np.linspace(0, W - 1, w).astype(np.float32)
    y0 = np.floor(yi).astype(np.int32); x0 = np.floor(xi).astype(np.int32)
    y1 = np.minimum(y0 + 1, H - 1); x1 = np.minimum(x0 + 1, W - 1)
    wy = (yi - y0)[:, None]; wx = (xi - x0)[None, :]
    top = a[y0][:, x0] * (1 - wx) + a[y0][:, x1] * wx
    bot = a[y1][:, x0] * (1 - wx) + a[y1][:, x1] * wx
    return top * (1 - wy) + bot * wy


# ---------------------------------------------------------------- 形变
def warp(img, flow, *, edge_fill="reflect"):
    """沿 flow 反向采样：img 为 (h,w,3)，flow 为 (h,w,2) 像素位移。

    edge_fill: 'reflect' 反射（避免黑边），'clamp' 边缘延展。
    """
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    sx = xx + flow[..., 0]
    sy = yy + flow[..., 1]
    if edge_fill == "reflect":
        sx = np.abs(sx); sy = np.abs(sy)
        sx = np.where(sx > w - 1, 2 * (w - 1) - sx, sx)
        sy = np.where(sy > h - 1, 2 * (h - 1) - sy, sy)
    sx = np.clip(sx, 0, w - 1.001)
    sy = np.clip(sy, 0, h - 1.001)
    x0 = sx.astype(np.int32); y0 = sy.astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1); y1 = np.minimum(y0 + 1, h - 1)
    wx = (sx - x0)[..., None]; wy = (sy - y0)[..., None]

    p00 = img[y0, x0]; p01 = img[y0, x1]; p10 = img[y1, x0]; p11 = img[y1, x1]
    top = p00 * (1 - wx) + p01 * wx
    bot = p10 * (1 - wx) + p11 * wx
    return top * (1 - wy) + bot * wy


def flow_morph(img_a, img_b, flow_ab, flow_ba, t, *, consistency=True):
    """两帧之间按流场做形态学插值（比交叉溶解干净，不会出现鬼影）。

    t=0 → A，t=1 → B。用 A→B 与 B→A 的流场做前向-后向一致性加权，
    遮挡区自动偏向"能看得见的那一帧"。
    """
    if t <= 0:
        return img_a
    if t >= 1:
        return img_b
    a = warp(img_a, flow_ab * t)
    b = warp(img_b, flow_ba * (1 - t))
    if not consistency:
        return a * (1 - t) + b * t
    # 一致性：两个流场互逆程度高 → 可信度高
    back = np.linalg.norm(flow_ab + _resize_flow(flow_ba, flow_ab.shape[:2]), axis=-1)
    conf = np.clip(1.0 - back / 6.0, 0, 1)
    wsum = conf * (1 - t) + conf * t + 1e-6
    out = (a * (conf * (1 - t))[..., None] + b * (conf * t)[..., None]) / wsum[..., None]
    # 低置信度区域退回简单溶解
    low = (conf < 0.35)[..., None]
    return np.where(low, a * (1 - t) + b * t, out)


def _resize_flow(f, shape):
    h, w = shape
    return np.stack([_resize_np(f[..., 0], (h, w)), _resize_np(f[..., 1], (h, w))], -1)


# ---------------------------------------------------------------- 光学流
def horn_schunck(a, b, *, iters=60, alpha=0.7, levels=4):
    """金字塔 Horn–Schunck 稠密光流（灰度输入，返回 (h,w,2)）。"""
    ga = a.mean(2) if a.ndim == 3 else a
    gb = b.mean(2) if b.ndim == 3 else b
    ga = (ga - ga.mean()) / (ga.std() + 1e-6)
    gb = (gb - gb.mean()) / (gb.std() + 1e-6)

    pyr_a, pyr_b = [ga], [gb]
    for _ in range(levels - 1):
        if min(pyr_a[-1].shape) < 40:
            break
        pyr_a.append(_down2(pyr_a[-1])); pyr_b.append(_down2(pyr_b[-1]))

    u = np.zeros_like(pyr_a[-1]); v = np.zeros_like(pyr_a[-1])
    for lv in range(len(pyr_a) - 1, -1, -1):
        ia, ib = pyr_a[lv], pyr_b[lv]
        if u.shape != ia.shape:
            u = _resize_np(u, ia.shape); v = _resize_np(v, ia.shape)
            u *= ia.shape[1] / max(1, u.shape[1]) if False else 1.0
        u, v = _hs_solve(ia, ib, u, v, iters, alpha)
    return np.stack([u, v], -1).astype(np.float32)


def _down2(a):
    h, w = a.shape
    h2, w2 = h // 2 * 2, w // 2 * 2
    a = a[:h2, :w2]
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


def _hs_solve(ia, ib, u, v, iters, alpha):
    # 空间梯度
    iy, ix = np.gradient((ia + ib) * 0.5)
    it = ib - ia
    k = np.ones((5, 5), np.float32) / 25.0
    a2 = alpha ** 2
    for _ in range(iters):
        ub = _box(u, k); vb = _box(v, k)
        num = ix * ub + iy * vb + it
        den = a2 + ix ** 2 + iy ** 2
        u = ub - ix * num / den
        v = vb - iy * num / den
    return u, v


def _box(a, k):
    """5x5 均值滤波（用累积和近似，快）。"""
    r = k.shape[0] // 2
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)), mode="constant")
    k2 = 2 * r + 1
    s = (c[k2:, k2:] - c[:-k2, k2:] - c[k2:, :-k2] + c[:-k2, :-k2])
    return (s / (k2 * k2)).astype(np.float32)


# ---------------------------------------------------------------- 快门
def shutter(sampler, n=3, jitter=False):
    """沿时间累积 N 个子帧 → 真实运动模糊（相机与被摄体都带）。

    sampler(u) 接收 0..1 的内部时刻，返回 (h,w,3) float 数组。
    """
    acc = None
    for i in range(n):
        u = (i + 0.5) / n
        f = sampler(u)
        acc = f if acc is None else acc + f
    return acc / n


# ---------------------------------------------------------------- 区域形变
def soft_band(h, w, y0, y1, x0=0.0, x1=1.0, feather=0.18):
    """生成带羽化的矩形遮罩（0..1），用于"只让这块动"。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ny, nx = yy / h, xx / w
    fy = max(1e-4, feather)
    my = np.clip((ny - y0) / fy, 0, 1) * np.clip((y1 - ny) / fy, 0, 1)
    mx = np.clip((nx - x0) / fy, 0, 1) * np.clip((x1 - nx) / fy, 0, 1)
    m = np.sqrt(np.clip(my, 0, 1) * np.clip(mx, 0, 1))
    return m.astype(np.float32)


def luminance_gate(img, lo, hi, softness=0.12):
    """按亮度挑区域（亮部=白袍/光，暗部=雾/影）。"""
    lum = img.mean(2) / 255.0
    return (np.clip((lum - lo) / max(1e-4, softness), 0, 1) *
            np.clip((hi - lum) / max(1e-4, softness), 0, 1)).astype(np.float32)


def organic_flow(h, w, noise, *, amp=6.0, scale=1.0, t=0.0, drift=(0.0, 0.0)):
    """由低频噪声驱动的有机形变场：同一块区域会像布/雾一样"呼吸"。

    noise 为可平铺分形噪声 (n,n)；通过相位平移实现随时间流动。
    """
    n = noise.shape[0]
    ox = int(t * 60 * scale) % n
    oy = int(t * 24 * scale) % n
    nx = np.roll(np.roll(noise, ox, 1), oy, 0)
    gx = np.gradient(nx, axis=1)
    gy = np.gradient(nx, axis=0)
    gx = _resize_np(gx.astype(np.float32), (h, w)) * (max(h, w) / n)
    gy = _resize_np(gy.astype(np.float32), (h, w)) * (max(h, w) / n)
    fx = gx * amp * scale + drift[0]
    fy = gy * amp * scale + drift[1]
    return np.stack([fx, fy], -1).astype(np.float32)
