#!/usr/bin/env python3
"""Render one 30 fps action-second from an existing continuous pose chain.

This is a diagnostic, not a master render. It deliberately disables broad parallax
and organic warp fields so temporal pose continuity can be judged without ripple-like
deformation. The 30 frames are interpolated from the shot's key poses; they are NOT
30 independently generated AI images.

Example:
  python3 scripts/render_1s_sequence_test.py --shot 15 \
      --out out/review/one_second_30f_shot15.mp4
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from render.lib.core import Cache, W, H  # noqa: E402
from render.lib.shot import Shot  # noqa: E402
from render.render_video import FPS, post, FF  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", type=int, default=15)
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "review", "one_second_30f.mp4"))
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--key-chain", default="", help="临时覆盖关键帧名，逗号分隔；仅用于试验")
    ap.add_argument("--key-ts", default="", help="临时覆盖 key_ts，逗号分隔")
    ap.add_argument("--morph-width", type=int, default=640,
                    help="关键帧光流计算宽度，增大可保细节但显著变慢")
    ap.add_argument("--low-conf", choices=("blend", "nearest"), default="blend",
                    help="低置信区域使用双帧混合或最近姿势；nearest 是实验项，不保证消除拖尾")
    a = ap.parse_args()
    if a.seconds <= 0 or a.seconds > 2:
        raise SystemExit("测试长度限制为 (0, 2] 秒")

    cfg = json.load(open(os.path.join(ROOT, "shots", "shots.json"), encoding="utf-8"))["shots"]
    base_meta = next((s for s in cfg if s["id"] == a.shot), None)
    if base_meta is None:
        raise SystemExit(f"shots.json 中没有镜头 {a.shot}")
    meta = dict(base_meta)
    motion = json.load(open(os.path.join(ROOT, "shots", "motion.json"), encoding="utf-8"))
    meta.update(motion.get(str(a.shot), {}))
    if a.key_chain:
        meta["key_chain"] = [x.strip() for x in a.key_chain.split(",") if x.strip()]
    if a.key_ts:
        meta["key_ts"] = [float(x.strip()) for x in a.key_ts.split(",") if x.strip()]
    if not meta.get("key_chain"):
        raise SystemExit(f"镜头 {a.shot} 没有 key_chain，无法做连续姿势测试")

    # 取动作链前 a.seconds 秒；不让画布水面/地面场扭曲污染本次测试。
    meta["t1"] = meta["t0"] + a.seconds
    meta["warps"] = []
    meta["parallax"] = []
    meta["morph_width"] = a.morph_width
    meta["morph_low_conf"] = a.low_conf
    meta["shutter"] = max(1, int(meta.get("shutter", 1)))
    n = int(round(a.seconds * FPS))
    cache = Cache(W, H)
    image_path = os.path.join(ROOT, "assets", "shots", meta["art"] + ".jpg")
    shot = Shot(meta, Image.open(image_path).convert("RGB"), cache, FPS)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cmd = [FF, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
           "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    rng = np.random.default_rng(2026)
    for i in range(n):
        img = shot.frame(i)
        img = post(img, cache, rng, i, meta, t=i / FPS)
        proc.stdin.write(np.clip(img, 0, 255).astype(np.uint8).tobytes())
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    rc = proc.wait()
    if rc:
        raise SystemExit(f"ffmpeg 失败 ({rc}): {err[-2000:]}")
    print(f"完成：镜头 {a.shot}，{n} 帧 / {FPS} fps / {a.seconds:.2f} s，无音频 → {a.out}")


if __name__ == "__main__":
    main()
