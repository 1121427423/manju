#!/usr/bin/env python3
"""素材预处理：
1) assets/shots/*_raw.png  →  16:9 裁切 + JPEG(q94) 的交付素材
2) 生成 keyart 联络表 docs/keyart_sheet.jpg
保持仓库轻量（PNG 原图不入库）。
"""
import os, glob, json
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "assets", "shots")
FONT = os.path.join(ROOT, "assets", "fonts", "Title-Serif.otf")


def crop169(im):
    w, h = im.size
    tw = int(min(w, h * 16 / 9)); th = int(tw * 9 / 16)
    return im.crop(((w - tw) // 2, (h - th) // 2, (w - tw) // 2 + tw, (h - th) // 2 + th))


def main():
    metas = json.load(open(os.path.join(ROOT, "shots", "shots.json")))["shots"]
    art2meta = {m["art"]: m for m in metas}
    made = []
    for f in sorted(glob.glob(os.path.join(SHOTS, "*_raw.png"))):
        name = os.path.basename(f).replace("_raw.png", "")
        im = crop169(Image.open(f).convert("RGB"))
        out = os.path.join(SHOTS, name + ".jpg")
        im.save(out, quality=94, subsampling=1, optimize=True, progressive=True)
        made.append((name, os.path.getsize(out), im.size))
        print(f"{name:24s} {im.size}  {os.path.getsize(out)/1024:.0f}KB")

    # 联络表
    if made:
        cols, tw = 4, 420
        th = int(tw * 9 / 16)
        rows = (len(made) + cols - 1) // cols
        pad, cap = 10, 26
        W = cols * (tw + pad) + pad
        H = rows * (th + pad + cap) + pad
        sheet = Image.new("RGB", (W, H), (12, 16, 20))
        d = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype(FONT, 15)
        except Exception:
            font = ImageFont.load_default()
        for i, (name, _, _) in enumerate(made):
            im = Image.open(os.path.join(SHOTS, name + ".jpg")).resize((tw, th), Image.LANCZOS)
            x = pad + (i % cols) * (tw + pad)
            y = pad + (i // cols) * (th + pad + cap)
            sheet.paste(im, (x, y))
            m = art2meta.get(name, {})
            label = f"{name}  {m.get('t0','')}-{m.get('t1','')}s"
            d.text((x + 2, y + th + 5), label, fill=(150, 190, 185), font=font)
        os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
        sheet.save(os.path.join(ROOT, "docs", "keyart_sheet.jpg"), quality=88, optimize=True)
        print("keyart sheet ->", sheet.size)


if __name__ == "__main__":
    main()
