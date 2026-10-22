# -*- coding: utf-8 -*-
"""逐镜量化主体局部运动：找出哪个镜头还是"静帧感"。

用法: python3 scripts/pershot_probe.py out/青冥·伞_40s.mp4
"""
import sys, os, json, subprocess
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
GW, GH = 320, 180
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def frames(path, t0, t1, fps=12):
    raw = subprocess.run([FF, "-v", "error", "-ss", str(t0), "-to", str(t1), "-i", path,
                          "-vf", "fps=%d,scale=%d:%d,format=gray" % (fps, GW, GH),
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         stdout=subprocess.PIPE).stdout
    n = len(raw) // (GW * GH)
    return np.frombuffer(raw[:n * GW * GH], np.uint8).reshape(n, GH, GW).astype(np.float32)


def phase(a, b):
    w = np.outer(np.hanning(GH), np.hanning(GW))
    A = np.fft.rfft2((a - a.mean()) * w)
    B = np.fft.rfft2((b - b.mean()) * w)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    c = np.fft.irfft2(R, s=a.shape)
    py, px = np.unravel_index(np.argmax(c), c.shape)
    return (px - GW if px > GW // 2 else px), (py - GH if py > GH // 2 else py)


def probe(path, t0, t1):
    F = frames(path, t0, t1)
    if len(F) < 4:
        return None
    out = []
    for i in range(len(F) - 1):
        dx, dy = phase(F[i], F[i + 1])
        reg = np.roll(np.roll(F[i], -dy, 0), -dx, 1)
        r = np.abs(F[i + 1] - reg)
        out.append(float(np.median(r[r > np.percentile(r, 60)])))
    return float(np.median(out))


if __name__ == "__main__":
    cand = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "out", "青冥·伞_40s.mp4")
    shots = json.load(open(os.path.join(ROOT, "shots", "shots.json"), encoding="utf-8"))["shots"]
    act = {10, 11, 12, 13, 15, 16, 17, 21}
    vals, actv = [], []
    for s in shots:
        v = probe(cand, s["t0"] + 0.15, s["t1"] - 0.1)
        vals.append(v)
        if s["id"] in act:
            actv.append(v)
        mark = "★" if s["id"] in act else " "
        print("%s %2d %-20s local=%6.2f" % (mark, s["id"], s["art"][:18], v))
    print("\n全片中位 %.2f ｜ 8 个动作镜中位 %.2f（参考片 35.00）"
          % (float(np.median(vals)), float(np.median(actv))))
