# -*- coding: utf-8 -*-
"""量化"这段片子是在动，还是在推静帧"。

方法：相邻两帧先用相位相关估**全局**位移（相机/整体平移），
再把全局位移配准掉，剩下的残差就是**主体局部运动**（衣袂、雾、水、能量）。
静帧 + 推拉 → 全局大、局部≈0；真动作 → 局部大。

用法: python3 scripts/motion_probe.py a.mp4 b.mp4 ...
"""
import sys, os, subprocess, json
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
GW, GH = 320, 180


def frames(path, fps=12, dur=None):
    cmd = [FF, "-v", "error", "-i", path]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-vf", "fps=%d,scale=%d:%d,format=gray" % (fps, GW, GH),
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE).stdout
    n = len(raw) // (GW * GH)
    return np.frombuffer(raw[:n * GW * GH], np.uint8).reshape(n, GH, GW).astype(np.float32)


def phase_shift(a, b):
    """相位相关估计 b 相对 a 的平移 (dx, dy)。"""
    fa = np.fft.rfft2(a - a.mean())
    fb = np.fft.rfft2(b - b.mean())
    R = fa * np.conj(fb)
    R /= (np.abs(R) + 1e-9)
    c = np.fft.irfft2(R, s=a.shape)
    p = np.unravel_index(np.argmax(c), c.shape)
    dy, dx = p
    if dy > GH // 2: dy -= GH
    if dx > GW // 2: dx -= GW
    return float(dx), float(dy)


def shift_img(a, dx, dy):
    """把 a 反向平移 (dx,dy)（双线性，FFT 相移）。"""
    fy = np.fft.fftfreq(a.shape[0])[:, None]
    fx = np.fft.rfftfreq(a.shape[1])[None, :]
    ph = np.exp(-2j * np.pi * (fx * dx + fy * dy))
    return np.fft.irfft2(np.fft.rfft2(a) * ph, s=a.shape).astype(np.float32)


def probe(path, dur=None):
    F = frames(path, dur=dur)
    if len(F) < 4:
        return None
    g, l = [], []
    for i in range(len(F) - 1):
        a, b = F[i], F[i + 1]
        dx, dy = phase_shift(a, b)
        gv = float(np.hypot(dx, dy))
        # 配准后残差 = 局部运动
        reg = shift_img(a, dx, dy)
        r = np.abs(b - reg)
        sel = r[r > np.percentile(r, 60)]
        # 纯白/纯黑帧（如白闪）残差全 0，sel 为空 -> 跳过该帧对，避免 nan 污染全片
        if sel.size < 64:
            g.append(gv)
            continue
        lv = float(np.median(sel))
        g.append(gv); l.append(lv)
    g = np.array(g); l = np.array(l)
    return dict(file=os.path.basename(path), n=len(F), fps_probe=12,
                global_px=round(float(np.median(g)), 2),
                local_px=round(float(np.median(l)), 2),
                local_mean=round(float(l.mean()), 2),
                local_p90=round(float(np.percentile(l, 90)), 2),
                motion_ratio=round(float(l.mean() / max(0.5, g.mean())), 2))


if __name__ == "__main__":
    rows = [probe(p) for p in sys.argv[1:]]
    rows = [r for r in rows if r]
    for r in rows:
        print("%-28s 全局 %6.2f  局部中位 %6.2f  局部均值 %6.2f  P90 %6.2f  比 %5.2f"
              % (r["file"], r["global_px"], r["local_px"], r["local_mean"],
                 r["local_p90"], r["motion_ratio"]))
    json.dump(rows, open("out/motion_probe.json", "w"), indent=1, ensure_ascii=False)
