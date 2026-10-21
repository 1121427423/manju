#!/usr/bin/env python3
"""从成片生成衍生图：联络表 + 海报 + 角色卡。

用法: python3 scripts/make_derived.py out/青冥·伞_40s.mp4
产出: out/contact_sheet.jpg / out/poster.jpg / out/character_cards.jpg
"""
import os, sys, subprocess, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = imageio_ffmpeg.get_ffmpeg_exe()
FONT = os.path.join(ROOT, "assets", "fonts", "Title-Serif.otf")


def grab(video, times, w=1280, h=720):
    out = []
    for t in times:
        raw = tempfile.mktemp(suffix=".raw")
        subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={w}:{h}", "-pix_fmt", "rgb24", "-f", "rawvideo", raw, "-y"])
        if os.path.exists(raw):
            a = np.fromfile(raw, dtype=np.uint8)
            os.remove(raw)
            if a.size == w * h * 3:
                out.append(Image.fromarray(a.reshape(h, w, 3)))
    return out


def contact_sheet(frames, path, cols=5, tw=384):
    th = int(tw * 9 / 16)
    rows = (len(frames) + cols - 1) // cols
    pad = 8
    W = cols * (tw + pad) + pad
    H = rows * (th + pad) + pad
    sheet = Image.new("RGB", (W, H), (10, 12, 15))
    for i, f in enumerate(frames):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + pad)
        sheet.paste(f.resize((tw, th), Image.LANCZOS), (x, y))
    sheet.save(path, quality=86, optimize=True)
    print("contact sheet", sheet.size, "->", path)


def poster(video, path):
    # 海报底图：优先"人物 + 伞"的全身镜（比极特写更适合做主视觉）
    im = None
    for t in (6.4, 6.0, 6.8, 11.2, 10.9):
        f = grab(video, [t], 1280, 720)
        if f:
            im = f[0]
            break
    if im is None:
        raise SystemExit("无法抽取海报底图")
    # 竖版海报 1200x1600
    PW, PH = 1200, 1600
    s = max(PW / im.width, PH / im.height)
    im2 = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
    l = (im2.width - PW) // 2
    t = int((im2.height - PH) * 0.42)
    im2 = im2.crop((l, t, l + PW, t + PH)).filter(ImageFilter.GaussianBlur(0.3))

    # 压暗上下 + 青绿渐变
    ov = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(PH):
        k = y / PH
        a = int(215 * max(0, (k - 0.55) / 0.45) ** 1.3 + 120 * max(0, (0.22 - k) / 0.22) ** 1.3)
        if a:
            d.line([(0, y), (PW, y)], fill=(6, 14, 18, min(240, a)))
    im2 = Image.alpha_composite(im2.convert("RGBA"), ov)
    d = ImageDraw.Draw(im2)

    f_title = ImageFont.truetype(FONT, 118)
    title = "青冥·伞"
    track = 10
    widths = [d.textlength(c, font=f_title) for c in title]
    total = sum(widths) + track * (len(title) - 1)
    x = PW / 2 - total / 2
    y = int(PH * 0.655)
    for c, cw in zip(title, widths):
        d.text((x, y), c, font=f_title, fill=(240, 250, 248, 255), stroke_width=3,
               stroke_fill=(20, 70, 62, 210))
        x += cw + track
    f_s = ImageFont.truetype(FONT, 34)
    s1 = "第 一 话 · 待 续"
    w1 = d.textlength(s1, font=f_s)
    d.text((PW / 2 - w1 / 2, y + 190), s1, font=f_s, fill=(201, 162, 75, 245))
    f_e = ImageFont.truetype(FONT, 21)
    e = "Q I N G M I N G  :  T H E   U M B R E L L A"
    we = d.textlength(e, font=f_e)
    d.text((PW / 2 - we / 2, y + 250), e, font=f_e, fill=(148, 198, 192, 210))
    d.line([(PW / 2 - 210, y + 168), (PW / 2 + 210, y + 168)], fill=(201, 162, 75, 90), width=1)

    f_t = ImageFont.truetype(FONT, 24)
    tag = "雨 · 石阵 · 一剑 · 与伞下的她"
    wt = d.textlength(tag, font=f_t)
    d.text((PW / 2 - wt / 2, int(PH * 0.115)), tag, font=f_t, fill=(210, 232, 228, 205))

    im2.convert("RGB").save(path, quality=92, optimize=True)
    print("poster ->", path)


def cards(path):
    """两张角色卡（定妆图 + 信息）"""
    a = Image.open(os.path.join(ROOT, "assets", "keyart", "CHAR_xuanluo.jpg")).convert("RGB")
    b = Image.open(os.path.join(ROOT, "assets", "keyart", "CHAR_zhaoxue.jpg")).convert("RGB")
    CW, CH = 800, 1000
    out = Image.new("RGB", (CW * 2 + 24, CH + 24), (10, 12, 15))
    for i, (im, name, sub, col) in enumerate([
            (a, "玄 罗", "九幽罗盘伞 · 箓雾 · 金铃", (95, 227, 192)),
            (b, "照 雪", "素霜剑 · 剑气 · 霜阵", (232, 244, 242))]):
        s = max(CW / im.width, CH / im.height)
        im2 = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        l = (im2.width - CW) // 2
        im2 = im2.crop((l, 0, l + CW, CH))
        d = ImageDraw.Draw(im2)
        ov = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
        do = ImageDraw.Draw(ov)
        do.rectangle([0, CH - 190, CW, CH], fill=(6, 12, 14, 200))
        im2 = Image.alpha_composite(im2.convert("RGBA"), ov)
        d = ImageDraw.Draw(im2)
        f1 = ImageFont.truetype(FONT, 62)
        f2 = ImageFont.truetype(FONT, 26)
        d.text((40, CH - 156), name, font=f1, fill=(*col, 255))
        d.text((42, CH - 74), sub, font=f2, fill=(200, 220, 216, 230))
        out.paste(im2.convert("RGB"), (12 + i * (CW + 12), 12))
    out.save(path, quality=90, optimize=True)
    print("character cards ->", path)


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "out", "青冥·伞_40s.mp4")
    frames = grab(video, np.arange(1.0, 39.0, 1.9).tolist())
    if not frames:
        print("无法抽帧，检查视频路径"); sys.exit(1)
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    contact_sheet(frames, os.path.join(ROOT, "out", "contact_sheet.jpg"))
    poster(video, os.path.join(ROOT, "out", "poster.jpg"))
    cards(os.path.join(ROOT, "out", "character_cards.jpg"))
