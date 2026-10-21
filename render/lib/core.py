"""图像/合成基础工具。全部基于 numpy + PIL，无 GPU 依赖。"""
import numpy as np
from PIL import Image, ImageFilter

W, H = 1280, 720          # 交付分辨率
SS = 1.0                  # 超采样系数（1.0 = 关闭，节省内存）


# ---------- 色彩 ----------
TEAL_DEEP = np.array([31, 107, 94], np.float32)
TEAL_GLOW = np.array([95, 227, 192], np.float32)
INK = np.array([12, 22, 32], np.float32)
STONE = np.array([110, 122, 128], np.float32)
COLD_WHITE = np.array([232, 244, 242], np.float32)
GOLD = np.array([201, 162, 75], np.float32)
GOLD_HOT = np.array([255, 231, 168], np.float32)


def np2img(a):
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def img2np(im):
    return np.asarray(im.convert("RGB"), np.float32)


def lerp(a, b, t):
    return a + (b - a) * t


def ease(t, kind="inout"):
    t = min(1.0, max(0.0, t))
    if kind == "inout":
        return t * t * (3 - 2 * t)
    if kind == "out":
        return 1 - (1 - t) ** 2
    if kind == "in":
        return t * t
    if kind == "out3":
        return 1 - (1 - t) ** 3
    return t


# ---------- 图像运算 ----------
def fit_canvas(im, w, h, overscan=1.0):
    """等比铺满 + 居中裁切，再按 overscan 放大（给运镜留边）。"""
    tw, th = int(w * overscan), int(h * overscan)
    s = max(tw / im.width, th / im.height)
    nw, nh = max(tw, int(im.width * s + 0.5)), max(th, int(im.height * s + 0.5))
    im = im.convert("RGB").resize((nw, nh), Image.LANCZOS)
    l, t = (nw - tw) // 2, (nh - th) // 2
    return im.crop((l, t, l + tw, t + th))


def crop169(im):
    """原生分辨率 16:9 居中裁切；若小于 1.02 倍交付宽则放大到 1.02 倍（保证锐度与余量）。"""
    w, h = im.size
    tw = int(min(w, h * 16 / 9)); th = int(tw * 9 / 16)
    im = im.crop(((w - tw) // 2, (h - th) // 2, (w - tw) // 2 + tw, (h - th) // 2 + th))
    if im.width < W * 1.02:
        s = W * 1.02 / im.width
        im = im.resize((int(im.width * s + .5), int(im.height * s + .5)), Image.LANCZOS)
    return im


def affine(im, zoom=1.0, pan=(0, 0), rot_deg=0.0, out_size=None):
    """以图像中心为锚点做 缩放+旋转+平移，输出 out_size（默认同源尺寸）。

    zoom=1 时输出为标准取景框（源图会被当作为运镜预留的超采画布）。
    """
    w, h = im.size
    ow, oh = out_size or (w, h)
    th = np.radians(rot_deg)
    c, s = np.cos(th), np.sin(th)
    z = max(0.2, zoom)
    a, b = c / z, s / z
    d, e = -s / z, c / z
    # 输出中心 → 源中心，再叠加平移
    cc = w / 2 - a * (ow / 2) - b * (oh / 2) + pan[0] / z
    ff = h / 2 - d * (ow / 2) - e * (oh / 2) + pan[1] / z
    return im.transform((ow, oh), Image.AFFINE, (a, b, cc, d, e, ff), resample=Image.BICUBIC)


def blur(im, r):
    return im.filter(ImageFilter.GaussianBlur(r))


def screen(a, b):
    return 255 - (255 - a) * (255 - b) / 255.0


def add_glow(base, glow, gain=1.0):
    """base/glow 为 float 数组（H,W,3）。"""
    return base + glow * gain


def radial_mask(w, h, cx, cy, r_in, r_out, power=1.6):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(1e-3, (r_out - r_in))
    t = np.clip((d - r_in / max(1e-3, (r_out - r_in))), 0, 1)
    m = 1.0 - t
    return np.clip(m, 0, 1) ** power


class Cache:
    def __init__(self, w, h):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.xx, self.yy = xx, yy
        nx, ny = (xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)
        r = np.sqrt(nx ** 2 + ny ** 2) / 1.414
        self.vignette = np.clip(1.0 - 0.62 * r ** 2.1, 0, 1)[..., None]
        self.r_norm = np.sqrt(nx ** 2 + ny ** 2)
        self.w, self.h = w, h
        rng = np.random.default_rng(7)
        # 可平铺的雾/噪声底图（多倍频）
        self.fog = self._tilenoise(512, rng, octaves=4)
        self.fog2 = self._tilenoise(512, rng, octaves=5)

    @staticmethod
    def _tilenoise(n, rng, octaves=4):
        acc = np.zeros((n, n), np.float32)
        amp = 1.0
        for o in range(octaves):
            s = 8 * 2 ** o
            g = rng.normal(size=(s, s)).astype(np.float32)
            t = np.asarray(Image.fromarray(((g - g.min()) / (np.ptp(g) + 1e-6) * 255).astype(np.uint8))
                           .resize((n, n), Image.BICUBIC), np.float32) / 255.0
            # 环向混合保证可平铺
            a = t + np.roll(t, n // 2, 0)
            a = a * 0.5
            acc += a * amp
            amp *= 0.55
        acc -= acc.min()
        acc /= (acc.max() + 1e-6)
        return acc
