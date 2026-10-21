"""程序化特效层。所有函数返回 HxWx3 float 数组（加色层用，或整幅替换）。

设计原则（对齐参考片）：能量 = 亮芯 + 柔边 + 拖尾 三层；每个特效都要"有呼吸"。
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
def C(c):
    """颜色归一化到 0..1，后续都乘"亮度增量(0-255)"。"""
    return np.asarray(c, np.float32) / 255.0


from .core import (np2img, img2np, radial_mask, ease, np as _np, Cache,
                   TEAL_GLOW, TEAL_DEEP, GOLD, GOLD_HOT, COLD_WHITE, blur, screen, lerp)


# ============================================================ 雨
class Rain:
    """三层不同深度的雨：远=细快、中=清晰、近=粗虚（散景）。"""

    def __init__(self, w, h, rng, n=260, angle=14.0):
        self.w, self.h, self.rng = w, h, rng
        self.angle = np.radians(angle)
        self.layers = []
        for i, (cnt, spd, ln, al, wid) in enumerate(
                [(int(n * 0.55), 900, 16, 38, 1), (int(n * 0.32), 1500, 34, 62, 1),
                 (int(n * 0.13), 2300, 70, 34, 3)]):
            self.layers.append(dict(
                x=rng.uniform(-w * 0.3, w * 1.3, cnt), y=rng.uniform(0, h, cnt),
                spd=rng.uniform(0.8, 1.2, cnt) * spd,
                ln=rng.uniform(0.7, 1.3, cnt) * ln,
                a=al, wid=wid))

    def draw(self, t, wind=1.0):
        img = Image.new("L", (self.w, self.h), 0)
        d = ImageDraw.Draw(img)
        dx, dy = np.sin(self.angle) * wind, np.cos(self.angle)
        for L in self.layers:
            L["y"] = (L["y"] + L["spd"] * (1 / 30.0)) % (self.h + 120)
            L["x"] = (L["x"] + L["spd"] * (1 / 30.0) * np.sin(self.angle) * 0.5 * wind) % (self.w + 200) - 100
            for x, y, ln, a in zip(L["x"], L["y"], L["ln"], np.full(len(L["x"]), L["a"])):
                d.line([(x, y), (x - dx * ln, y - dy * ln)], fill=int(a), width=L["wid"])
        img = img.filter(ImageFilter.GaussianBlur(0.6 if self.layers[0] else 0))
        arr = np.asarray(img, np.float32) / 255.0
        return arr[..., None] * C([205, 230, 235]) * 210


# ============================================================ 雾 / 体积光
def fog_overlay(cache: Cache, t, speed=0.06, density=0.34, tint=TEAL_GLOW, scale=1.0):
    n = cache.fog.shape[0]
    ox = int(t * speed * 90) % n
    oy = int(t * speed * 26) % n
    a = np.roll(np.roll(cache.fog, ox, 1), oy, 0)
    a = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize(
        (int(cache.w * scale), int(cache.h * scale)), Image.BILINEAR), np.float32) / 255.0
    a = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((cache.w, cache.h), Image.BILINEAR),
                   np.float32) / 255.0
    a = np.clip((a - 0.42) * 2.1, 0, 1) ** 1.5
    # 雾贴地：下半部分更浓
    a *= np.clip((cache.yy / cache.h) * 1.9 - 0.25, 0, 1)
    return a[..., None] * tint * density


def light_shaft(cache, cx, w, t, gain=1.0, tint=TEAL_GLOW):
    """竖直光柱（塔顶光柱 / 施法光）。"""
    x = (cache.xx - cx + cache.w / 2) / w
    col = np.exp(-x ** 2 * 3.2)
    fl = 0.82 + 0.18 * np.sin(t * 2.7) + 0.08 * np.sin(t * 7.3)
    return (col * fl * gain)[..., None] * C(tint) * 120


# ============================================================ 粒子
class Sparks:
    def __init__(self, w, h, rng, n=90, cx=None, cy=None, power=1.0, tint=None, grav=1500):
        self.w, self.h, self.rng = w, h, rng
        cx = w * 0.5 if cx is None else cx
        cy = h * 0.5 if cy is None else cy
        ang = rng.uniform(0, 2 * np.pi, n)
        sp = rng.uniform(0.25, 1.0, n) ** 0.6 * power * 900
        self.p = np.stack([np.full(n, cx), np.full(n, cy)], 1)
        self.v = np.stack([np.cos(ang) * sp, np.sin(ang) * sp * 0.72 - 180 * power], 1)
        self.life = rng.uniform(0.35, 1.0, n)
        self.age = np.zeros(n)
        self.n, self.grav = n, grav
        self.tint = tint if tint is not None else GOLD_HOT

    def step(self, dt):
        self.v[:, 1] += self.grav * dt
        self.v *= (1 - 2.0 * dt)
        self.p += self.v * dt
        self.age += dt

    def draw(self):
        img = Image.new("L", (self.w, self.h), 0)
        d = ImageDraw.Draw(img)
        for i in range(self.n):
            if self.age[i] > self.life[i]:
                continue
            k = 1 - self.age[i] / self.life[i]
            x, y = self.p[i]
            vx, vy = self.v[i] * 0.012
            a = int(255 * min(1, k * 1.6) * (0.55 + 0.45 * np.sin(i * 3.1 + self.age[i] * 40)))
            d.line([(x, y), (x - vx, y - vy)], fill=max(0, a), width=2 if k > 0.5 else 1)
        img = img.filter(ImageFilter.GaussianBlur(0.7))
        arr = np.asarray(img, np.float32) / 255.0
        return arr[..., None] * self.tint * 0.9


class Embers:
    """向上飘的绿烬，全片气氛层。"""

    def __init__(self, w, h, rng, n=70, tint=TEAL_GLOW):
        self.w, self.h = w, h
        self.x = rng.uniform(0, w, n)
        self.y = rng.uniform(0, h, n)
        self.s = rng.uniform(0.6, 2.2, n)
        self.sp = rng.uniform(18, 70, n)
        self.ph = rng.uniform(0, 6.28, n)
        self.tint = tint

    def draw(self, t):
        img = Image.new("L", (self.w, self.h), 0)
        d = ImageDraw.Draw(img)
        for i in range(len(self.x)):
            y = (self.y[i] - self.sp[i] * t) % (self.h + 40)
            x = self.x[i] + 22 * np.sin(t * 0.9 + self.ph[i])
            r = self.s[i]
            a = int(120 + 90 * np.sin(t * 3 + self.ph[i]))
            d.ellipse([x - r, y - r, x + r, y + r], fill=max(0, a))
        img = img.filter(ImageFilter.GaussianBlur(2.2))
        return np.asarray(img, np.float32)[..., None] / 255.0 * self.tint * 0.85


# ============================================================ 光学
def bloom(img, th=0.62, gain=0.85, tint=TEAL_GLOW, anamorphic=0.0):
    a = img / 255.0
    lum = a.max(2, keepdims=True)
    bright = np.clip((a - th) / (1 - th + 1e-6), 0, 1) * np.clip(lum * 1.6, 0, 1)
    b = np2img(bright * 255)
    w, h = b.size
    parts = []
    for div, wt in [(4, 0.55), (10, 0.35), (24, 0.28)]:
        parts.append((np.asarray(blur(b.resize((w // div, h // div), Image.BILINEAR), 3.0)
                                .resize((w, h), Image.BILINEAR), np.float32) / 255.0) * wt)
    g = sum(parts)
    g = g * (0.55 + 0.45 * (g / (g.max() + 1e-6)))
    out = img + g * tint * gain
    if anamorphic > 0:
        streak = np2img(g * 255).resize((w, max(2, h // 8)), Image.BILINEAR)
        streak = streak.filter(ImageFilter.GaussianBlur(6)).resize((w, h), Image.BILINEAR)
        out = out + np.asarray(streak, np.float32)[..., None] / 255.0 * tint * anamorphic * 0.8
    return out


def chromatic(img, amt=1.0, cache: Cache = None):
    if amt <= 0.01:
        return img
    h, w = img.shape[:2]
    k = 1.0 + 0.0016 * amt
    r = np2img(img)
    ch_r = np.asarray(r.split()[0], np.float32)
    ch_g = np.asarray(r.split()[1], np.float32)
    ch_b = np.asarray(r.split()[2], np.float32)
    def scale(ch, s):
        im = Image.fromarray(np.clip(ch, 0, 255).astype(np.uint8))
        cx, cy = w / 2, h / 2
        return np.asarray(im.transform((w, h), Image.AFFINE,
                                       (1 / s, 0, cx - cx / s, 0, 1 / s, cy - cy / s),
                                       resample=Image.BILINEAR), np.float32)
    return np.stack([scale(ch_r, k), ch_g, scale(ch_b, 1 / k)], 2)


def vignette(img, cache, strength=1.0):
    return img * (1 - (1 - cache.vignette) * strength)


def grain(img, rng, amt=5.0):
    n = rng.normal(0, 1, img.shape[:2]).astype(np.float32)
    n = np.asarray(Image.fromarray(((n * 0.25 + 0.5) * 255).clip(0, 255).astype(np.uint8))
                   .filter(ImageFilter.GaussianBlur(0.5)), np.float32) / 255.0
    n = (n - 0.5) * 2
    lum = img.mean(2, keepdims=True) / 255.0
    mod = 0.45 + 0.85 * (1 - np.abs(lum - 0.35))
    return img + n[..., None] * amt * mod * 3.0


def grade(img, lift=0.0, teal_shadow=0.30, contrast=1.06, sat=1.05, warm_hl=0.06,
          gamma=0.98):
    a = img / 255.0
    # 亮度曲线
    a = np.clip(a, 0, 1) ** gamma
    a = (a - 0.5) * contrast + 0.5 + lift
    # 阴影偏青、高光偏暖（经典 teal & gold）
    lum = a.mean(2, keepdims=True)
    sh = (1 - np.clip(lum * 1.8, 0, 1)) ** 1.4
    hl = np.clip((lum - 0.55) * 1.9, 0, 1)
    a = a * (1 - sh * teal_shadow * np.array([1.0, 0.35, 0.28])) \
          + sh * teal_shadow * a * np.array([0.55, 1.15, 1.05])
    a = a + hl * warm_hl * np.array([1.0, 0.72, 0.35])
    # 饱和度
    g = a.mean(2, keepdims=True)
    a = g + (a - g) * sat
    # 提黑：暗部不纯黑
    a = a * (1 - 0.06) + 0.045 * np.array([0.30, 0.55, 0.60])
    return np.clip(a, 0, 1) * 255


# ============================================================ 大特效
def impact_flash(img, cache, cx, cy, t, dur=0.30, power=1.0, tint=GOLD_HOT):
    """撞击：径向冲光 + 星芒 + 全屏提亮。"""
    if t > dur:
        return img
    k = t / dur
    env = (1 - k) ** 2.2 * power
    m = radial_mask(cache.w, cache.h, cx, cy, 0, 260 + 700 * ease(k, "out"), power=1.9)
    out = img + m[..., None] ** 1.4 * C(tint) * 900 * env
    # 星芒
    ang = 10
    streak = np.zeros((cache.h, cache.w), np.float32)
    for i in range(ang):
        a = np.pi * i / ang + 0.2
        dx, dy = np.cos(a), np.sin(a)
        for s in np.arange(0, 620, 8):
            x, y = int(cx + dx * s), int(cy + dy * s)
            if 0 <= x < cache.w and 0 <= y < cache.h:
                streak[y, x] = max(streak[y, x], np.exp(-s / (220 * (1 - k) + 40)))
    st = Image.fromarray((streak * 255).clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.5))
    out = out + np.asarray(st, np.float32)[..., None] / 255.0 * C(tint) * 700 * env
    # 全屏提亮（前 4 帧）
    if k < 0.22:
        out = out + (1 - k / 0.22) * 38
    return out


def energy_orb(img, cache, cx, cy, r, t, tint=TEAL_GLOW, power=1.0):
    d = np.sqrt((cache.xx - cx) ** 2 + (cache.yy - cy) ** 2)
    core = np.exp(-(d / (r * 0.42)) ** 2)
    ring = np.exp(-((d - r) / (r * 0.30)) ** 2) * (0.6 + 0.4 * np.sin(t * 9))
    halo = np.exp(-(d / (r * 2.1)) ** 1.4) * 0.35
    n = cache.fog
    tex = np.roll(n, int(t * 40) % n.shape[0], 1)
    tex = np.asarray(Image.fromarray((tex * 255).astype(np.uint8)).resize((cache.w, cache.h),
                                                                         Image.BILINEAR), np.float32) / 255
    swirl = (0.5 + 0.5 * tex) * (core + ring * 0.7)
    g = (core * 1.9 + ring * 0.8 + halo) * power
    out = img + g[..., None] * C(tint) * 520
    out = out + swirl[..., None] * 230 * power
    return out


def blade_light(img, cache, p0, p1, t, grow=1.0, tint=np.array([255, 240, 200], np.float32),
                width=9.0, power=1.0):
    """沿 p0→p1 的剑光/光刃。grow 0→1 表示出鞘/挥出。"""
    if grow <= 0:
        return img
    x0, y0 = p0
    x1, y1 = lerp(np.array(p0, np.float32), np.array(p1, np.float32), ease(min(1, grow), "out"))
    layer = Image.new("L", (cache.w, cache.h), 0)
    d = ImageDraw.Draw(layer)
    d.line([(x0, y0), (x1, y1)], fill=255, width=int(width * 2))
    layer = layer.filter(ImageFilter.GaussianBlur(width * 0.9))
    a = np.asarray(layer, np.float32) / 255.0
    core = Image.new("L", (cache.w, cache.h), 0)
    ImageDraw.Draw(core).line([(x0, y0), (x1, y1)], fill=255, width=max(1, int(width * 0.28)))
    c = np.asarray(core.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255.0
    return img + a[..., None] * C(tint) * 400 * power + c[..., None] * 460 * power


def ice_spikes(img, cache, t, seed=3, tint=np.array([190, 240, 255], np.float32), power=1.0):
    """冰晶从地面炸出成林。t 0→1 生长。"""
    rng = np.random.default_rng(seed)
    layer = Image.new("L", (cache.w, cache.h), 0)
    d = ImageDraw.Draw(layer)
    n = 26
    for i in range(n):
        bx = rng.uniform(-0.1, 1.1) * cache.w
        bw = rng.uniform(18, 70)
        bh = rng.uniform(0.25, 1.0) * cache.h * 0.95
        dist = abs(bx - cache.w / 2) / (cache.w / 2)
        delay = dist * 0.35 + rng.uniform(0, 0.18)
        k = np.clip((t - delay) / 0.5, 0, 1)
        if k <= 0:
            continue
        h = bh * ease(k, "out3")
        lean = rng.uniform(-0.22, 0.22)
        tipx, tipy = bx + lean * h, cache.h + 20 - h
        poly = [(bx - bw / 2, cache.h + 30), (bx + bw / 2, cache.h + 30),
                (tipx + bw * 0.14, tipy + h * 0.18), (tipx, tipy)]
        d.polygon(poly, fill=int(200 * min(1, k * 1.5)))
        d.line([(bx, cache.h + 20), (tipx, tipy)], fill=255, width=2)
    soft = np.asarray(layer.filter(ImageFilter.GaussianBlur(1.4)), np.float32) / 255
    hard = np.asarray(layer, np.float32) / 255
    edge = np.clip(hard - soft * 0.55, 0, 1)
    return img + hard[..., None] * C(tint) * 130 * power + edge[..., None] * 300 * power


def rift(img, cache, t, seed=11, cx=None, cy=None):
    """空间裂缝：撕裂遮罩（内部压黑 + 边缘发光 + 噪声撕边）。t 0→1。"""
    rng = np.random.default_rng(seed)
    cx = cache.w * 0.5 if cx is None else cx
    cy = cache.h * 0.42 if cy is None else cy
    pts = []
    n = 18
    for i in range(n):
        a = i / n * 2 * np.pi
        r = 1 + 0.35 * np.sin(a * 3 + 1) + rng.uniform(-0.12, 0.12)
        pts.append((np.cos(a) * r, np.sin(a) * r))
    k = ease(min(1, t), "out")
    sx = cache.w * 0.55 * k
    sy = cache.h * 0.10 + cache.h * 0.26 * k
    mask = Image.new("L", (cache.w, cache.h), 0)
    ImageDraw.Draw(mask).polygon([(cx + px * sx, cy + py * sy) for px, py in pts], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    m = np.asarray(mask, np.float32) / 255
    edge = np.asarray(mask.filter(ImageFilter.GaussianBlur(9)), np.float32) / 255 - m
    edge = np.clip(edge * 2.4, 0, 1)
    inner = m * (0.10 + 0.25 * cache.fog[:cache.h, :cache.w] if False else 0.12)
    out = img * (1 - m[..., None] * 0.96) + m[..., None] * np.array([4, 10, 12], np.float32)
    out = out + edge[..., None] * C(TEAL_GLOW) * 480
    # 裂缝内绿焰流动
    n2 = np.roll(cache.fog, int(t * 120) % cache.fog.shape[0], 1)[:cache.h, :cache.w]
    out = out + (n2 * m)[..., None] * C(TEAL_GLOW) * 160 * (0.5 + 0.5 * np.sin(t * 4))
    return out


def speed_lines(img, cache, t, angle=0.0, n=90, power=0.6, seed=5):
    rng = np.random.default_rng(int(t * 1000) % 9999 + seed)
    layer = Image.new("L", (cache.w, cache.h), 0)
    d = ImageDraw.Draw(layer)
    ca, sa = np.cos(angle), np.sin(angle)
    for i in range(n):
        # 极坐标 → 从中心向外
        a = rng.uniform(0, 2 * np.pi)
        r0 = rng.uniform(0.35, 1.0) * max(cache.w, cache.h) * 0.55
        ln = rng.uniform(60, 260) * (0.6 + power)
        x0, y0 = cache.w / 2 + np.cos(a) * r0, cache.h / 2 + np.sin(a) * r0 * 0.62
        d.line([(x0, y0), (x0 + ca * ln, y0 + sa * ln)], fill=int(rng.uniform(40, 110)), width=rng.choice([1, 1, 2]))
    arr = np.asarray(layer.filter(ImageFilter.GaussianBlur(1.1)), np.float32) / 255
    return img + arr[..., None] * C([230, 250, 250]) * 230 * power


def whiteout(img, k=1.0, tint=np.array([255, 255, 255], np.float32)):
    """白光爆：抬亮度 + 降饱和 + 叠加白。"""
    if k <= 0:
        return img
    a = img / 255.0
    g = a.mean(2, keepdims=True)
    a = g + (a - g) * (1 - 0.85 * k)
    a = a * (1 - 0.55 * k) + k * 0.9
    return np.clip(a, 0, 1) * 255


def pupil_pulse(img, cache, cx, cy, r, k, inner=0.30):
    """瞳孔发光：只给虹膜一圈 + 极弱内芯，避免整块糊白。"""
    d = np.sqrt((cache.xx - cx) ** 2 + (cache.yy - cy) ** 2)
    ring = np.exp(-((d - r * 0.62) / (r * 0.30)) ** 2) * 150
    core = np.exp(-(d / (r * inner)) ** 2) * 55
    return img + (ring + core)[..., None] * C(TEAL_GLOW) * k


def corruption(img, cache, t, k=1.0, seed=13):
    """皮肤下蔓延的绿色血管光纹（用于胸口受创/手部咒纹）。"""
    rng = np.random.default_rng(seed)
    layer = Image.new("L", (cache.w, cache.h), 0)
    d = ImageDraw.Draw(layer)
    origins = [(cache.w * rng.uniform(0.2, 0.8), cache.h * rng.uniform(0.25, 0.85)) for _ in range(5)]
    for ox, oy in origins:
        for b in range(9):
            x, y = ox, oy
            ang = rng.uniform(0, 6.28)
            for s in range(int(30 * min(1, t * 1.6))):
                ang += rng.uniform(-0.5, 0.5)
                x += np.cos(ang) * 6
                y += np.sin(ang) * 6
                r = 2.0 * (1 - s / 40)
                d.ellipse([x - r, y - r, x + r, y + r], fill=int(220 * (1 - s / 45)))
    soft = np.asarray(layer.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255
    hard = np.asarray(layer.filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255
    return img + (soft * 0.9 + hard * 1.5)[..., None] * C(TEAL_GLOW) * 240 * k
