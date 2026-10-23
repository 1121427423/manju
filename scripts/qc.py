#!/usr/bin/env python3
"""质检：把成片与参考片做同口径数值对比。

用法: python3 scripts/qc.py out/xx.mp4 original-720p.mp4
指标: 时长 / 亮度均值 / 暗部占比 / 饱和度 / 色偏 / 帧差(运动量) / 切点数 / ASL / 响度
"""
import sys, os, subprocess, tempfile, wave
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()


def probe(path):
    p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
    d = {}
    for line in p.stderr.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            d["dur"] = int(h) * 3600 + int(m) * 60 + float(s)
        if "Video:" in line and "1280" in line or ("Video:" in line and "Stream" in line):
            for tok in line.split(","):
                tok = tok.strip()
                if "x" in tok and tok.split("x")[0].isdigit() and tok.split("x")[1][:3].isdigit():
                    d["size"] = tok
                if "fps" in tok:
                    d["fps"] = tok
    return d


def video_stats(path, fps=10, w=320, h=180):
    raw = tempfile.mktemp(suffix=".raw")
    subprocess.run([FF, "-v", "error", "-i", path, "-vf", f"scale={w}:{h},fps={fps}",
                    "-pix_fmt", "rgb24", "-f", "rawvideo", raw, "-y"])
    x = np.fromfile(raw, dtype=np.uint8).reshape(-1, h, w, 3).astype(np.float32)
    os.remove(raw)
    lum = x.mean(3)
    mo = np.r_[0, np.abs(np.diff(x, axis=0)).mean(axis=(1, 2, 3))]
    teal = float((x[..., 1] + x[..., 2] - 2 * x[..., 0]).mean())
    gold = float((x[..., 0] + x[..., 1] - 2 * x[..., 2]).mean())
    sat = float((x.max(3) - x.min(3)).mean())
    th = mo.mean() + mo.std()
    spikes = [round(i / fps, 2) for i in range(1, len(mo)) if mo[i] > th * 1.6]
    cuts = len(cuts_by_scene(path))
    return dict(lum=float(lum.mean()), lum_p5=float(np.percentile(lum, 5)),
                lum_p95=float(np.percentile(lum, 95)), sat=sat, teal=teal, gold=gold,
                motion=float(mo.mean()), spikes=spikes, cuts=cuts,
                dur=len(x) / fps)


def frame_luma(path, w=192, h=108):
    """逐帧亮度曲线（全帧率），只用于判断第二次触发是不是闪光。"""
    raw = tempfile.mktemp(suffix=".raw")
    subprocess.run([FF, "-v", "error", "-i", path, "-vf", f"scale={w}:{h}",
                    "-pix_fmt", "rgb24", "-f", "rawvideo", raw, "-y"])
    a = np.fromfile(raw, dtype=np.uint8)
    if os.path.exists(raw):
        os.remove(raw)
    if a.size < w * h * 3:
        return None
    n = a.size // (w * h * 3)
    return a[: n * w * h * 3].reshape(n, h, w, 3).mean(axis=(1, 2, 3))


def cuts_by_scene(path, th=0.30):
    """场景切点，已合并"同一次剪辑的多次触发"（与 reviewer 同规则、独立实现）。

    1) 间隔 ≤0.07s：同一转场被相邻帧各报一次；
    2) 间隔 <0.40s 且后一次触发处亮度 ≥ 前次的 1.15 倍：硬切紧跟的亮闪被误判成转场。
    只压暗的连续快剪不会满足 2)，因此参考片真实的 0.23s 快剪不会被吞。
    """
    p = subprocess.run([FF, "-hide_banner", "-i", path,
                        "-vf", f"select='gt(scene,{th})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    raw = [float(t.split(":")[1]) for t in p.stderr.split() if t.startswith("pts_time:")]
    dur = probe(path).get("dur", 0) or 0
    lum = frame_luma(path)
    fps = (len(lum) / dur) if (lum is not None and dur > 0) else 30.0
    kept = []
    for t in sorted(raw):
        if kept:
            gap = t - kept[-1]
            if gap <= 0.07:
                continue
            if gap < 0.40 and lum is not None:
                i, j = int(round(kept[-1] * fps)), int(round(t * fps))
                if 0 <= i < len(lum) and 0 <= j < len(lum) and lum[i] > 1:
                    if lum[j] / lum[i] >= 1.15:
                        continue
        kept.append(t)
    return kept


def audio_stats(path):
    wav = tempfile.mktemp(suffix=".wav")
    subprocess.run([FF, "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", "44100", wav, "-y"])
    try:
        w = wave.open(wav)
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        w.close()
    finally:
        if os.path.exists(wav):
            os.remove(wav)
    rms = float(np.sqrt((x ** 2).mean()))
    return dict(rms_db=20 * np.log10(rms + 1e-9),
                peak_db=20 * np.log10(np.abs(x).max() + 1e-9), ch=x.shape[-1])


def report(a, b):
    sa, sb = video_stats(a), video_stats(b)
    au = audio_stats(a) if has_audio(a) else None
    bu = audio_stats(b) if has_audio(b) else None
    rows = [
        ("时长(s)", sa["dur"], sb["dur"]),
        ("亮度均值", sa["lum"], sb["lum"]),
        ("暗部p5", sa["lum_p5"], sb["lum_p5"]),
        ("高光p95", sa["lum_p95"], sb["lum_p95"]),
        ("饱和度", sa["sat"], sb["sat"]),
        ("青绿偏移teal", sa["teal"], sb["teal"]),
        ("金色偏移gold", sa["gold"], sb["gold"]),
        ("帧差(运动量)", sa["motion"], sb["motion"]),
        ("硬切数", sa["cuts"], sb["cuts"]),
        ("平均镜头长(s)", sa["dur"] / max(1, sa["cuts"]), sb["dur"] / max(1, sb["cuts"])),
    ]
    print(f"{'指标':<16}{'成片':>12}{'参考片':>12}{'偏差':>12}")
    print("-" * 52)
    for k, x, y in rows:
        d = (x - y) / (abs(y) + 1e-9) * 100
        print(f"{k:<16}{x:>12.2f}{y:>12.2f}{d:>11.1f}%")
    if au and bu:
        print("-" * 52)
        print(f"{'RMS(dBFS)':<16}{au['rms_db']:>12.2f}{bu['rms_db']:>12.2f}"
              f"{(au['rms_db']-bu['rms_db']):>+11.1f} dB")
        print(f"{'峰值(dBFS)':<16}{au['peak_db']:>12.2f}{bu['peak_db']:>12.2f}"
              f"{(au['peak_db']-bu['peak_db']):>+11.1f} dB")


def has_audio(path):
    p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
    return "Audio:" in p.stderr


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "out/青冥·伞_40s.mp4"
    b = sys.argv[2] if len(sys.argv) > 2 else "original-720p.mp4"
    report(a, b)
