"""单镜头合成：运镜 + 特效 + 调色，输出一帧 RGB float 数组。"""
import numpy as np
from PIL import Image, ImageFilter
from .core import (W, H, Cache, np2img, img2np, affine, crop169, ease, blur,
                   TEAL_GLOW, GOLD, GOLD_HOT, COLD_WHITE, radial_mask)
from . import vfx
from .vfx import Rain, Sparks, Embers

# 画布 = 素材原生的 16:9 裁切（不做无谓放大，保证锐度）；zoom=1 即完整取景框
SCALE = 1.0


class Shot:
    def __init__(self, meta, base_im, cache: Cache, fps=30):
        self.m = meta
        self.fps = fps
        self.n = max(1, int(round((meta["t1"] - meta["t0"]) * fps)))
        self.cache = cache
        x0, y0, x1, y1 = meta.get("crop", (0.0, 0.0, 1.0, 1.0))
        im = base_im.crop((int(x0 * base_im.width), int(y0 * base_im.height),
                           int(x1 * base_im.width), int(y1 * base_im.height)))
        # 画布预留 30% 余量：任何 zoom ≤ 1.24 的运镜都不会采样到画布外（否则会出现黑边）
        MARGIN = 1.30
        self.canvas = crop169(im).resize((int(W * MARGIN + 0.5), int(H * MARGIN + 0.5)),
                                         Image.LANCZOS)
        self.w, self.h = self.canvas.size
        self.k = W / self.w                  # 画布 → 输出 的比例
        self.vfx = set(meta.get("vfx", []))
        rng = np.random.default_rng(1000 + meta["id"])
        self.rng = rng
        if "rain" in self.vfx:
            self.rain = Rain(W, H, rng, n=300, angle=meta.get("rain_angle", 13))
        if "embers" in self.vfx or "dust" in self.vfx:
            self.embers = Embers(W, H, rng, n=90)
        if "sparks" in self.vfx:
            self.sparks = Sparks(W, H, rng, n=int(meta.get("spark_n", 110)),
                                 cx=W * 0.5, cy=H * 0.48, power=meta.get("spark_power", 1.0))
        self._spark_acc = 0.0
        self.lightning_t = [0.12, 0.58] if "lightning" in self.vfx else []

    # ---------------------------------------------------------------- 运镜
    def cam(self, i):
        m, t = self.m, i / max(1, self.n - 1)
        e = ease(t, m.get("ease", "inout"))
        z0, z1 = m["zoom"]
        # 运镜幅度 ×1.35：参考片的帧差 ≈21，静帧路线需要更强的运动量才不显"僵"
        base = z0 + (z1 - z0) * e
        zoom = min(1.24, max(0.92, 1.0 + (base - 1.0) * 1.35))
        pan = (m.get("pan", (0, 0))[0] * e * 1.3, m.get("pan", (0, 0))[1] * e * 1.3)
        rot = m.get("rot", 0.0) * t
        sh = m.get("shake", 0.0)
        # 全镜头轻微手持（0.55px / 0.05°），让静帧路线也有"被拍"的感觉
        if True:
            tt0 = i / self.fps
            pan = (pan[0] + np.sin(tt0 * 1.7 + m["id"]) * 0.55,
                   pan[1] + np.cos(tt0 * 1.3 + m["id"] * 1.7) * 0.45)
            rot += np.sin(tt0 * 1.1 + m["id"]) * 0.05
        if sh > 0:
            tt = i / self.fps
            # 两层正弦 + 冲击衰减
            imp = np.exp(-tt * 6.0)
            jx = np.sin(tt * 71.3 + m["id"]) * 0.55 + np.sin(tt * 133.1) * 0.35
            jy = np.cos(tt * 61.7 + m["id"] * 2) * 0.55 + np.sin(tt * 149.3) * 0.32
            pan = (pan[0] + jx * sh * (0.35 + imp), pan[1] + jy * sh * (0.35 + imp))
            rot += np.sin(tt * 43.0) * sh * 0.035
        return zoom, pan, rot

    # ---------------------------------------------------------------- 特效
    def fx(self, img, i):
        c = self.cache
        tt = i / self.fps                       # 镜头内秒数
        dur = (self.m["t1"] - self.m["t0"])
        p = tt / max(1e-3, dur)                 # 0→1 进度
        V = self.vfx

        if "rain" in V:
            img = img + self.rain.draw(tt, wind=self.m.get("wind", 1.0))
        if "water" in V:
            # 水面涟漪：贴地窄带 + 缓慢横向漂移的亮斑
            band = np.clip(1 - (c.yy - c.h * 0.72) / (c.h * 0.22), 0, 1) ** 2
            n = np.roll(c.fog2, int(tt * 30) % c.fog2.shape[0], 1)
            n = n[:c.h, :c.w] if n.shape[0] >= c.h else n
            n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((c.w, c.h), Image.BILINEAR),
                           np.float32) / 255
            img = img + (band * n)[..., None] * (np.array([150, 220, 230], np.float32) / 255) * 85
        if "fog" in V:
            img = img + vfx.fog_overlay(c, tt + self.m["id"] * 3.1,
                                        density=self.m.get("fog_density", 0.30),
                                        scale=1.0)
        if "light" in V:
            img = img + vfx.light_shaft(c, self.m.get("light_x", c.w * 0.5),
                                        self.m.get("light_w", 70), tt,
                                        gain=self.m.get("light_gain", 1.0))
        if "lightning" in V:
            for k, at in enumerate(self.lightning_t):
                dt = tt - at
                if 0 < dt < 0.16:
                    f = (1 - dt / 0.16) ** 2
                    sky = np.clip(1 - c.yy / (c.h * 0.75), 0, 1)[..., None]
                    img = img + sky * (np.array([210, 232, 255], np.float32) / 255) * 300 * f
        if "swirl" in V:
            # 旋涡雾：极坐标旋转
            n = c.fog
            ang = tt * 0.9
            swirl = np.roll(n, int(ang * 60) % n.shape[0], 1)
            s = np.asarray(Image.fromarray((swirl * 255).astype(np.uint8)).resize((c.w, c.h), Image.BILINEAR),
                           np.float32) / 255
            m = radial_mask(c.w, c.h, c.w / 2, c.h / 2, 40, c.w * 0.55, power=1.2)
            img = img + (s * m)[..., None] * (TEAL_GLOW / 255) * 120
        if "pupil" in V:
            img = vfx.pupil_pulse(img, c, c.w / 2, c.h * 0.5, c.h * 0.22,
                                  0.55 + 0.45 * np.sin(tt * 3.4))
        if "demon_eye" in V:
            img = vfx.pupil_pulse(img, c, c.w * 0.5, c.h * 0.45, c.h * 0.30,
                                  0.45 + 0.55 * np.sin(tt * 2.1) ** 2)
        if "corrupt" in V:
            img = vfx.corruption(img, c, tt, k=min(1, p * 1.6))
        if "ice" in V:
            img = vfx.ice_spikes(img, c, p, seed=self.m["id"])
        if "rift" in V:
            img = vfx.rift(img, c, min(1, p * 1.25), cx=c.w * 0.5, cy=c.h * 0.40,
                           seed=self.m["id"])
        if "orb" in V:
            grow = ease(min(1, p * 2.2), "out")
            img = vfx.energy_orb(img, c, c.w * 0.5, c.h * 0.46,
                                 c.h * 0.30 * (0.35 + 0.65 * grow), tt, power=0.5 + 0.9 * p)
        if "blade" in V:
            img = vfx.blade_light(img, c, (c.w * 0.12, c.h * 0.72), (c.w * 0.95, c.h * 0.22),
                                  tt, grow=min(1, p * 1.8), power=self.m.get("blade_power", 1.0))
        if "speedlines" in V:
            img = vfx.speed_lines(img, c, tt, angle=np.radians(6),
                                  power=min(1.0, p * 2.0) * self.m.get("sl_power", 0.75))
        if "sparks" in V:
            sub = 3
            dt = 1.0 / self.fps / sub
            drawn = False
            for _ in range(sub):
                self.sparks.step(dt)
            if int(i % 2) == 0 or p < 0.6:
                img = img + self.sparks.draw()
        if "dust" in V:
            dm = vfx.fog_overlay(c, tt * 2.0, speed=0.5, density=0.55,
                                 tint=np.array([180, 200, 205], np.float32), scale=1.6)
            img = img + dm * min(1, p * 1.5)
        if "embers" in V or "dust" in V:
            img = img + self.embers.draw(tt)
        if "flash_impact" in V:
            at = self.m.get("flash_t", 0.16)
            dt = tt - at
            if 0 <= dt < 0.34:
                img = vfx.impact_flash(img, c, c.w * 0.5, c.h * 0.47, dt,
                                       power=self.m.get("flash_power", 1.0))
        if "whiteout" in V:
            k = np.clip((tt - 0.10) / 0.22, 0, 1)
            k = k * (1 - np.clip((tt - 1.25) / 0.30, 0, 1))
            img = vfx.whiteout(img, k ** 0.8)
        return img

    # ---------------------------------------------------------------- 一帧
    def frame(self, i):
        zoom, pan, rot = self.cam(i)
        im = affine(self.canvas, self.k * zoom, (pan[0] * self.k, pan[1] * self.k), rot,
                    out_size=(W, H))
        img = img2np(im)
        # 镜头内的轻微曝光呼吸（让静帧"活"起来）
        fl = 1.0 + 0.012 * np.sin(i / self.fps * 2.3 + self.m["id"])
        img = img * fl
        img = self.fx(img, i)
        return img

    # gradient（黑场/白场）由主循环统一处理
