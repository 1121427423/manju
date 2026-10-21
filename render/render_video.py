#!/usr/bin/env python3
"""把关键帧序列 + 运镜 + 特效 + 调色 + 音轨，渲染成成片。

用法:
  python3 -m render.render_video                     # 全片
  python3 -m render.render_video --only 1,2,3        # 只渲染前三个镜头（调试）
  python3 -m render.render_video --no-audio          # 无声
"""
import os, sys, json, argparse, subprocess, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from render.lib.core import (W, H, Cache, np2img, img2np, crop169, ease, blur,
                             TEAL_GLOW, TEAL_DEEP, GOLD, GOLD_HOT, COLD_WHITE, INK)
from render.lib.shot import Shot
from render.lib import vfx
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = imageio_ffmpeg.get_ffmpeg_exe()
FONT_PATH = os.path.join(ROOT, "assets", "fonts", "Title-Serif.otf")
FPS = 30


# ------------------------------------------------------------------ 后期
def post(img, cache, rng, i, meta):
    v = set(meta.get("vfx", []))
    ani = 0.55 if ("flash_impact" in v or "whiteout" in v) else 0.0
    img = vfx.bloom(img, th=0.70, gain=0.42, tint=np.array([140, 225, 215], np.float32),
                    anamorphic=ani * 0.8)
    # 校准：亮度 65±2 / p5≈8 / sat≈33（对齐参考片 0-15s 段实测值）
    img = vfx.grade(img, lift=0.004, teal_shadow=0.20, contrast=1.10, sat=0.90, warm_hl=0.05)
    ca = 1.8 if ("shake" in v or "flash_impact" in v) else 0.6
    img = vfx.chromatic(img, ca)
    img = vfx.vignette(img, cache, 0.92)
    # 顶部压暗 + 中心轻微提亮（把视线压到人物上）
    top = np.clip(cache.yy / (H * 0.55), 0, 1)[..., None] ** 0.8
    img = img * (0.82 + 0.18 * top)
    ctr = np.exp(-((cache.xx - W * 0.5) ** 2 / (2 * (W * 0.30) ** 2)
                   + (cache.yy - H * 0.52) ** 2 / (2 * (H * 0.34) ** 2)))[..., None]
    img = img * (1 + 0.075 * ctr)
    img = vfx.grain(img, rng, 1.5)
    return img


def fade(img, k):
    return img * k


# ------------------------------------------------------------------ 字幕
CAP_STYLE = dict(size=27, color=(226, 240, 238), alpha=232, spacing=1.9)


def draw_caption(img, text, k, y_frac=0.80, x_frac=0.085, vertical=True):
    """左下竖排小字，逐字浮现。"""
    if k <= 0 or not text:
        return img
    im = np2img(img)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = ImageFont.truetype(FONT_PATH, CAP_STYLE["size"])
    chars = [c for c in text]
    x = int(W * x_frac)
    y = int(H * y_frac)
    step = CAP_STYLE["size"] + CAP_STYLE["spacing"] * 3
    n = len(chars)
    for idx, ch in enumerate(chars):
        # 每个字依次浮现
        a0 = idx / max(1, n)
        aa = np.clip((k - a0 * 0.6) / 0.4, 0, 1)
        if aa <= 0:
            continue
        a = int(CAP_STYLE["alpha"] * aa)
        yy = y - idx * step
        d.text((x, yy), ch, font=font, fill=(*CAP_STYLE["color"], a),
               stroke_width=1, stroke_fill=(10, 20, 22, int(a * 0.55)))
    # 柔和发光
    glow = layer.filter(ImageFilter.GaussianBlur(6))
    base = im.convert("RGBA")
    base.alpha_composite(glow)
    base.alpha_composite(layer)
    return np.asarray(base.convert("RGB"), np.float32)


# ------------------------------------------------------------------ 片名卡
def render_title(meta, base_im, cache, i, n):
    t = i / max(1, n - 1)
    dur = meta["t1"] - meta["t0"]
    tt = i / FPS
    # 背景：场景图重度虚化 + 压暗 + 缓慢推近
    im = base_im.crop((0, 0, base_im.width, base_im.height)).resize(
        (int(W * 1.12), int(H * 1.12)), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(16))
    z = 1.02 + 0.02 * t
    im = im.resize((int(im.width * z), int(im.height * z)), Image.BILINEAR)
    l = (im.width - W) // 2; tp = (im.height - H) // 2
    im = im.crop((l, tp, l + W, tp + H))
    img = img2np(im) * 0.42
    # 暗部渐变 + 中央聚光
    img = img * (0.45 + 0.55 * np.exp(-((cache.xx - W / 2) ** 2 + (cache.yy - H * 0.45) ** 2)
                                     / (2 * (W * 0.45) ** 2))[..., None])
    img = img + vfx.fog_overlay(cache, tt, speed=0.25, density=0.22)
    img = vfx.grade(img, teal_shadow=0.45, contrast=1.05, sat=0.95)

    # 旋转金环
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ring)
    cx, cy = W // 2, int(H * 0.44)
    rr = 196
    rot = tt * 12
    for j in range(72):
        a0 = np.radians(rot + j * 5)
        r2 = rr + (14 if j % 6 == 0 else (7 if j % 3 == 0 else 0))
        d.line([(cx + np.cos(a0) * rr, cy + np.sin(a0) * rr),
                (cx + np.cos(a0) * r2, cy + np.sin(a0) * r2)],
               fill=(201, 162, 75, int(40 + 55 * (j % 6 == 0))), width=1)
    ring = ring.filter(ImageFilter.GaussianBlur(0.6))
    base = np2img(img).convert("RGBA")
    base.alpha_composite(ring)

    # 文字
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    k1 = np.clip((tt - 0.20) / 1.5, 0, 1)
    k2 = np.clip((tt - 1.10) / 1.4, 0, 1)
    k3 = np.clip((tt - 1.90) / 1.2, 0, 1)

    f_main = ImageFont.truetype(FONT_PATH, 104)
    title = "青冥 · 伞"
    # 字距拉开
    tw = sum(d.textlength(c, font=f_main) + 18 for c in title)
    x = cx - tw / 2
    y = cy - 60
    for c in title:
        a = int(255 * k1)
        if a > 3:
            d.text((x, y), c, font=f_main, fill=(238, 248, 246, a),
                   stroke_width=2, stroke_fill=(30, 107, 94, int(a * 0.8)))
        x += d.textlength(c, font=f_main) + 18 * k1

    f_sub = ImageFont.truetype(FONT_PATH, 26)
    sub = "第 一 话 · 待 续"
    sw = d.textlength(sub, font=f_sub)
    d.text((cx - sw / 2, cy + 108), sub, font=f_sub,
           fill=(201, 162, 75, int(240 * k2)))

    f_en = ImageFont.truetype(FONT_PATH, 17)
    en = "Q I N G M I N G  :  T H E   U M B R E L L A"
    ew = d.textlength(en, font=f_en)
    d.text((cx - ew / 2, cy + 152), en, font=f_en, fill=(150, 200, 195, int(200 * k3)))

    if k3 > 0:
        line_w = int(190 * k3)
        d.line([(cx - line_w, cy + 190), (cx + line_w, cy + 190)],
               fill=(201, 162, 75, int(120 * k3)), width=1)

    glow = lay.filter(ImageFilter.GaussianBlur(14))
    base.alpha_composite(glow)
    base.alpha_composite(glow)
    base.alpha_composite(lay)
    img = np.asarray(base.convert("RGB"), np.float32)

    # 结尾渐黑
    outk = 1 - np.clip((tt - (dur - 1.0)) / 1.0, 0, 1) ** 0.8
    return img * outk


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "preview.mp4"))
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--crf", type=int, default=18)
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "shots", "shots.json")))
    metas = cfg["shots"]
    only = set(int(x) for x in args.only.split(",") if x.strip()) if args.only else None
    cache = Cache(W, H)
    rng = np.random.default_rng(2026)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    todo = []
    for m in metas:
        if only and m["id"] not in only:
            continue
        art = m["art"]
        if art == "TITLE":
            base = Image.open(os.path.join(ROOT, "assets", "keyart", "SCENE_altar.jpg")).convert("RGB")
        else:
            p = os.path.join(ROOT, "assets", "shots", art + ".jpg")
            if not os.path.exists(p):
                print(f"!! 缺少素材 {art}.jpg —— 跳过镜头 {m['id']}")
                continue
            base = Image.open(p).convert("RGB")
        todo.append((m, base))
    if not todo:
        print("没有可渲染的镜头"); return

    cmd = [FF, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(args.fps), "-i", "-", "-an",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    t_start = time.time()
    total = 0
    for m, base in todo:
        n = max(1, int(round((m["t1"] - m["t0"]) * args.fps)))
        is_title = m["art"] == "TITLE"
        shot = None if is_title else Shot(m, base, cache, args.fps)
        for i in range(n):
            if is_title:
                img = render_title(m, base, cache, i, n)
                img = vfx.grain(img, rng, 1.6)
            else:
                img = shot.frame(i)
                img = post(img, cache, rng, i, m)
                if m.get("caption"):
                    k = np.clip((i / args.fps - 0.35) / 0.9, 0, 1)
                    k *= 1 - np.clip((i / args.fps - ((m["t1"] - m["t0"]) - 0.6)) / 0.6, 0, 1)
                    img = draw_caption(img, m["caption"], k)
                if m.get("trans") == "fadein":
                    img = fade(img, ease(i / (args.fps * 0.7), "out"))
            proc.stdin.write(np.clip(img, 0, 255).astype(np.uint8).tobytes())
            total += 1
        el = time.time() - t_start
        print(f"  镜头 {m['id']:2d} {m['art']:16s} {n:3d}帧 累计{total:4d} "
              f"{el:5.1f}s ({total/max(el,1e-6):.1f} fps)", flush=True)
    proc.stdin.close()
    proc.wait()

    if not args.no_audio:
        from render.lib.audio import build, write_wav
        wav = os.path.join(ROOT, "out", "score.wav")
        if not os.path.exists(wav):
            write_wav(wav, build())
        tmp = args.out.replace(".mp4", "_mux.mp4")
        subprocess.run([FF, "-y", "-i", args.out, "-i", wav, "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", tmp],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        os.replace(tmp, args.out)
    print(f"完成 → {args.out}  ({os.path.getsize(args.out)/1e6:.1f} MB, {total} 帧)")


if __name__ == "__main__":
    main()
