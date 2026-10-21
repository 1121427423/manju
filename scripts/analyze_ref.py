#!/usr/bin/env python3
"""复现《00-参考视频拆解.md》里的全部量化数据。

用法:  python3 scripts/analyze_ref.py original-720p.mp4
依赖:  numpy, imageio-ffmpeg (自带 ffmpeg 二进制)
"""
import subprocess, sys, os, wave, tempfile
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    return subprocess.run([FF, "-v", "error", *args], capture_output=True)


def probe(src):
    out = subprocess.run([FF, "-hide_banner", "-i", src], capture_output=True, text=True)
    return out.stderr


def scene_cuts(src, th=0.30):
    p = run(["-hide_banner", "-i", src, "-vf", f"select='gt(scene,{th})',showinfo",
             "-an", "-f", "null", "-"])
    txt = p.stderr.decode()
    return [float(t.split(":")[1]) for t in txt.split() if t.startswith("pts_time:")]


def frame_stats(src, w=320, h=180, fps=10):
    raw = tempfile.mktemp(suffix=".raw")
    run(["-i", src, "-vf", f"scale={w}:{h},fps={fps}", "-pix_fmt", "rgb24", "-f", "rawvideo", raw, "-y"])
    x = np.fromfile(raw, dtype=np.uint8).reshape(-1, h, w, 3).astype(np.float32)
    os.remove(raw)
    lum = x.mean(axis=3)
    mo = np.r_[0, np.abs(np.diff(x, axis=0)).mean(axis=(1, 2, 3))]
    teal = (x[..., 1] + x[..., 2] - 2 * x[..., 0]).mean()
    gold = (x[..., 0] + x[..., 1] - 2 * x[..., 2]).mean()
    return x, lum, mo, teal, gold, fps


def audio_env(src, sr=44100):
    wav = tempfile.mktemp(suffix=".wav")
    run(["-i", src, "-vn", "-ac", "2", "-ar", str(sr), wav, "-y"])
    w = wave.open(wav)
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    w.close()
    os.remove(wav)
    x = x.reshape(-1, 2).mean(axis=1)
    hop = int(sr * 0.1)
    env = np.array([20 * np.log10(np.sqrt((x[i:i + hop] ** 2).mean()) + 1e-12)
                    for i in range(0, len(x) - hop, hop)])
    d = np.diff(env)
    onsets = []
    for i in np.where(d > 6)[0]:
        t = round(float(i * 0.1), 2)
        if not onsets or t - onsets[-1] > 0.35:
            onsets.append(t)
    return env, onsets


def main(src):
    print("=" * 60)
    print(probe(src))
    print("hard cuts(th=0.30s):", scene_cuts(src))
    x, lum, mo, teal, gold, fps = frame_stats(src)
    print(f"frames={len(x)}  duration={len(x)/fps:.2f}s")
    print(f"global lum={lum.mean():.1f}  teal={teal:.1f}  gold={gold:.1f}")
    for s in range(0, int(len(x) / fps), 2):
        a, b = int(s * fps), int(min((s + 2) * fps, len(x)))
        print(f"{s:2d}-{s+2:2d}s lum={lum[a:b].mean():5.1f} motion={mo[a:b].mean():5.1f} "
              f"peak={mo[a:b].max():5.1f}")
    th = mo.mean() + mo.std()
    print("motion spikes:", [round(i / fps, 1) for i in range(1, len(mo)) if mo[i] > th * 1.6])
    env, onsets = audio_env(src)
    print(f"audio median={np.median(env):.1f}dB peak={env.max():.1f}dB p90={np.percentile(env, 90):.1f}dB")
    print("audio onsets:", onsets)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "original-720p.mp4")
