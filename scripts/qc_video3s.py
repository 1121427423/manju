#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一提示词不同版本的出片 QC 对比 —— 把"看起来好一点"变成可对比的数。

针对 v1 的三处偏差各给一个数:
  开场停顿偏长   → onset_s(首次明显运动的时间) / start_static_s(起手静止段长度)
  女方挡击反应弱 → right_E(接触窗口内右半画面运动能量, 女剑客在右侧)
  碰撞闪光偏强   → spark.max_frac(高亮像素占画面比例) / spark.dur_s(高亮持续帧数)

同时给首末帧与参考图的 NCC, 用来确认"双锚没跑偏"。

用法:
  python3 qc_video3s.py --a <v1.mp4> --b <v2.mp4> [--json out.json] [--sheet cmp.jpg]
"""
import argparse, json, os, subprocess, sys
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFS = os.path.join(ROOT, "out", "review", "video3s_refs")
W, H, FPS = 320, 180, 24
REF_START = os.path.join(REFS, "00_start.jpg")
REF_END = os.path.join(REFS, "02_end.jpg")


def gray_frames(path, dur=4.0):
    """按 24fps 抽成 (n,H,W) uint8 灰度, 尺寸压到 320x180 —— 只比结构, 不比细节。"""
    p = subprocess.run(["ffmpeg", "-v", "error", "-t", str(dur), "-i", path,
                        "-vf", f"fps={FPS},scale={W}:{H}", "-pix_fmt", "gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    if p.returncode != 0:
        sys.exit(f"ffmpeg 抽帧失败: {path}\n{p.stderr.decode()[:300]}")
    n = len(p.stdout) // (W * H)
    return np.frombuffer(p.stdout[:n * W * H], np.uint8).reshape(n, H, W)


def rgb_frames(path, dur=4.0):
    p = subprocess.run(["ffmpeg", "-v", "error", "-t", str(dur), "-i", path,
                        "-vf", f"fps={FPS},scale={W}:{H}", "-pix_fmt", "rgb24",
                        "-f", "rawvideo", "-"], capture_output=True)
    if p.returncode != 0:
        sys.exit(f"ffmpeg 抽帧失败: {path}")
    n = len(p.stdout) // (W * H * 3)
    return np.frombuffer(p.stdout[:n * W * H * 3], np.uint8).reshape(n, H, W, 3)


def ncc(a, b):
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a -= a.mean()
    b -= b.mean()
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a.dot(b) / d) if d else 0.0


def ref_gray(path):
    return np.asarray(Image.open(path).convert("L").resize((W, H), Image.LANCZOS),
                      dtype=np.float64)


def analyze(path, label):
    g = gray_frames(path)
    c = rgb_frames(path)
    n = min(len(g), len(c))
    g, c = g[:n], c[:n]
    t = np.arange(n) / FPS

    # 帧间运动图: 与前一帧的绝对差(首帧补 0), 逐帧均值即运动曲线
    dm = np.zeros((n, H, W), np.int16)
    dm[1:] = np.abs(g[1:].astype(np.int16) - g[:-1].astype(np.int16))
    d = dm.astype(np.float64).mean(axis=(1, 2))

    thresh = max(3.0, 1.8 * float(np.median(d[1:6])))  # 以前 5 帧为基线
    onset = None
    for i in range(1, n - 1):
        if d[i] > thresh and d[i + 1] > thresh:
            onset = float(t[i])
            break
    peak_i = int(np.argmax(d))

    # 火花/闪光: 三种掩膜各有用处 ——
    #   flash  = 近纯白(min RGB>=245): 碰撞高光。实测 v1 雨丝在 320x180 下到不了这个阈值
    #            (0.83s 前恒为 0.000%), 所以它只反映爆发, 不是雨。
    #   gold   = 暖色高亮: 提示词要求的"金色火花"; v1 实测 0.000%(出的是青白闪光), 可作对照。
    R = c[..., 0].astype(np.int16)
    G = c[..., 1].astype(np.int16)
    B = c[..., 2].astype(np.int16)
    flash = ((R >= 245) & (G >= 245) & (B >= 245)).mean(axis=(1, 2))
    gold = ((R >= 195) & (G >= 145) & (B <= 155) & (R - B >= 55)).mean(axis=(1, 2))
    # bloom = 泛白光斑的"总占面"(min RGB>=195): 白闪+金火花都算进去, 这才是观感上的"光太强"
    bloom = (np.minimum(np.minimum(R, G), B) >= 195).mean(axis=(1, 2))
    bloom_on = bloom[bloom > 0.002]
    spark_max = float(flash.max())
    spark_t = float(t[int(np.argmax(flash))])
    # 闪光"持续帧数": 占比超 0.2% 画面的帧数(低于此视为噪点)
    spark_frames = int((flash > 0.002).sum())
    gold_max = float(gold.max())

    half = W // 2
    win = (t >= 0.2) & (t <= 1.3)
    left_E = float(dm[win][:, :, :half].mean())
    right_E = float(dm[win][:, :, half:].mean())

    return {"label": label, "file": path, "frames": n, "duration_s": round(n / FPS, 3),
            "motion_onset_s": round(onset, 2) if onset is not None else None,
            "start_static_s": round(onset, 2) if onset is not None else None,
            "peak_s": round(float(t[peak_i]), 2), "peak_diff": round(float(d[peak_i]), 1),
            "mean_diff": round(float(d[1:].mean()), 1),
            "flash": {"max_frac": round(spark_max, 4), "at_s": round(spark_t, 2),
                      "frames_over_0.2pct": spark_frames, "gold_max_frac": round(gold_max, 4)},
            "bloom": {"max_frac": round(float(bloom.max()), 4),
                      "at_s": round(float(t[int(np.argmax(bloom))]), 2),
                      "mean_frac_while_on": round(float(bloom_on.mean()) if bloom_on.size else 0.0, 4),
                      "frames_over_0.2pct": int((bloom > 0.002).sum())},
            "motion_energy": {"left": round(left_E, 1), "right": round(right_E, 1),
                              "window": "0.2-1.3s"},
            "ncc_first_vs_start": round(ncc(g[0], ref_gray(REF_START)), 3),
            "ncc_last_vs_end": round(ncc(g[-1], ref_gray(REF_END)), 3)}


def sheet(a, b, out_jpg, times):
    imgs_a, imgs_b = [], []
    import tempfile
    tmp = tempfile.mkdtemp()
    for i, tt in enumerate(times):
        for src, box in ((a, imgs_a), (b, imgs_b)):
            p = os.path.join(tmp, f"{os.path.basename(src)[:6]}_{i}.png")
            subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{tt:.2f}", "-i", src,
                            "-frames:v", "1", p], capture_output=True)
            if os.path.exists(p):
                box.append(Image.open(p).convert("RGB"))
    if not imgs_a or not imgs_b:
        return None
    cw, ch = 420, 236
    cols = len(times)
    canvas = Image.new("RGB", (cw * cols, ch * 2 + 8), (10, 12, 16))
    for i in range(cols):
        canvas.paste(imgs_a[i].resize((cw, ch)), (i * cw, 0))
        canvas.paste(imgs_b[i].resize((cw, ch)), (i * cw, ch + 8))
    canvas.save(out_jpg, quality=88)
    return out_jpg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="基准版(通常是 v1)")
    ap.add_argument("--b", required=True, help="新版本(通常是 v2)")
    ap.add_argument("--label-a", default="v1")
    ap.add_argument("--label-b", default="v2")
    ap.add_argument("--json", default="")
    ap.add_argument("--sheet", default="")
    a = ap.parse_args()

    A = analyze(a.a, a.label_a)
    B = analyze(a.b, a.label_b)
    out = {"a": A, "b": B}
    if a.sheet:
        times = [i * 3.0 / 7 for i in range(8)]
        print("sheet ->", sheet(a.a, a.b, a.sheet, times))
    if a.json:
        json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    keys = ["motion_onset_s", "peak_s", "mean_diff"]
    print(f"{'metric':<26}{a.label_a:>10}{a.label_b:>10}")
    for k in keys:
        print(f"{k:<26}{str(A[k]):>10}{str(B[k]):>10}")
    for k in ("max_frac", "at_s", "frames_over_0.2pct", "gold_max_frac"):
        print(f"{'flash.' + k:<26}{str(A['flash'][k]):>10}{str(B['flash'][k]):>10}")
    for k in ("max_frac", "at_s", "mean_frac_while_on", "frames_over_0.2pct"):
        print(f"{'bloom.' + k:<26}{str(A['bloom'][k]):>10}{str(B['bloom'][k]):>10}")
    for k in ("left", "right"):
        print(f"{'energy.' + k:<26}{str(A['motion_energy'][k]):>10}{str(B['motion_energy'][k]):>10}")
    for k in ("ncc_first_vs_start", "ncc_last_vs_end"):
        print(f"{k:<26}{str(A[k]):>10}{str(B[k]):>10}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
