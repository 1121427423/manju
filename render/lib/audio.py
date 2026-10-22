"""程序化声音设计：雨 / 风 / drone / 弦乐 Pad / 金铃 / 剑鸣 / 撞击 / 雷 / 冰碎 / 空间撕裂。

全部用 numpy 合成，不依赖任何采样库 —— 也正因如此，音色干净、无版权问题。
对齐参考片的实测包络：中位 RMS ≈ -17.4 dB，峰值 ≈ -8.7 dB，动态被压平。
"""
import numpy as np

SR = 44100
DUR = 40.0
N = int(SR * DUR)


def _t(dur):
    return np.arange(int(SR * dur)) / SR


def _rng(seed):
    return np.random.default_rng(seed)


# ---------------------------------------------------------------- 基础滤波
def lowpass(x, cutoff, order=2):
    """一阶低通级联（RC），cutoff 可为标量或逐样本数组。"""
    y = x.astype(np.float64, copy=True)
    a = np.exp(-2 * np.pi * np.clip(cutoff, 20, SR / 2 - 100) / SR)
    for _ in range(order):
        out = np.empty_like(y)
        acc = 0.0
        if np.isscalar(a) or a.ndim == 0:
            for i in range(len(y)):          # 标量走快速路径
                acc = a * acc + (1 - a) * y[i]
                out[i] = acc
        else:
            for i in range(len(y)):
                acc = a[i] * acc + (1 - a[i]) * y[i]
                out[i] = acc
        y = out
    return y


def lowpass_fast(x, cutoff):
    """用频域做陡峭低通（对长噪声更高效）。"""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def highpass_fast(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 - 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def bandpass_fast(x, lo, hi):
    return highpass_fast(lowpass_fast(x, hi), lo)


def env_ar(n, attack, release, curve=2.0):
    a = max(1, int(attack * SR)); r = max(1, int(release * SR))
    e = np.ones(n)
    a = min(a, n); e[:a] = np.linspace(0, 1, a) ** 0.6
    r = min(r, n); e[-r:] *= np.linspace(1, 0, r) ** curve
    return e


def place(buf, sig, at, gain=1.0, pan=0.0):
    """把单声道片段叠加到立体声总线（等功率声像）。"""
    i = int(at * SR)
    if i >= buf.shape[1]:
        return
    n = min(len(sig), buf.shape[1] - i)
    l = np.cos((pan + 1) * np.pi / 4) * gain
    r = np.sin((pan + 1) * np.pi / 4) * gain
    buf[0, i:i + n] += sig[:n] * l
    buf[1, i:i + n] += sig[:n] * r


# ---------------------------------------------------------------- 音源
def make_rain(dur=DUR, seed=1):
    rng = _rng(seed)
    n = int(SR * dur)
    x = rng.normal(0, 1, n)
    hiss = bandpass_fast(x, 700, 9000) * 0.16
    # 近处雨幕的湿度：中频宽噪声
    hiss += bandpass_fast(rng.normal(0, 1, n), 200, 1800) * 0.09
    # 缓慢起伏（雨势变化）
    mod = 0.75 + 0.25 * np.sin(2 * np.pi * 0.07 * np.arange(n) / SR + 1.2)
    hiss *= mod
    # 水滴：随机短衰减正弦
    out = hiss.copy()
    for _ in range(320):
        at = rng.uniform(0, dur)
        f = rng.uniform(900, 3800)
        d = rng.uniform(0.02, 0.09)
        t = _t(d)
        s = np.sin(2 * np.pi * f * t) * np.exp(-t * 55) * rng.uniform(0.02, 0.10)
        out[int(at * SR):int(at * SR) + len(s)] += s[:max(0, n - int(at * SR))]
    return out


def make_wind(dur=DUR, seed=2):
    rng = _rng(seed)
    n = int(SR * dur)
    x = lowpass_fast(rng.normal(0, 1, n), 420) * 0.5
    lfo = 0.55 + 0.45 * np.sin(2 * np.pi * 0.11 * np.arange(n) / SR)
    return x * lfo


def make_drone(dur=DUR):
    n = int(SR * dur)
    t = np.arange(n) / SR
    base = 41.2
    s = np.zeros(n)
    for f, a in [(base, 0.55), (base * 2, 0.28), (base * 2.66, 0.16), (base * 1.5, 0.12)]:
        for det in (-0.12, 0.12):
            s += np.sin(2 * np.pi * (f + det) * t) * a * 0.5
    s *= 0.7 + 0.3 * np.sin(2 * np.pi * 0.05 * t)
    # 低频轰鸣涌起（用于结尾）
    swell = np.clip((t - 27) / 9, 0, 1) ** 1.4
    s += np.sin(2 * np.pi * 28 * t) * 0.35 * swell
    return s * 0.42


def make_pad(chords, dur=DUR, seed=3):
    """慢起音的弦乐 pad（D 小调色彩）。chords: [(start, end, [freqs])]"""
    n = int(SR * dur)
    out = np.zeros(n)
    for (t0, t1, freqs) in chords:
        i0, i1 = int(t0 * SR), min(n, int(t1 * SR))
        if i1 <= i0:
            continue
        tt = np.arange(i1 - i0) / SR
        seg = np.zeros(i1 - i0)
        for f in freqs:
            for det in (-0.4, 0.0, 0.42):
                ph = np.random.default_rng(hash((f, det)) % 9999).uniform(0, 6.28)
                seg += np.sin(2 * np.pi * (f + det) * tt + ph) * 0.6
                seg += np.sin(4 * np.pi * (f + det) * tt + ph) * 0.12
        seg /= len(freqs) * 3
        a = int(min(len(seg) * 0.55, 2.6 * SR))
        r = int(min(len(seg) * 0.6, 2.2 * SR))
        e = np.ones(len(seg))
        e[:a] = np.linspace(0, 1, a) ** 0.7
        e[-r:] = np.linspace(1, 0, r) ** 1.3
        out[i0:i1] += seg * e
    return lowpass_fast(out, 3200) * 0.5


def make_bell(f0=520, dur=2.6, seed=4):
    t = _t(dur)
    rng = _rng(seed)
    s = np.zeros(len(t))
    for k, (mult, amp, dec) in enumerate([(1.0, 1.0, 1.6), (2.76, 0.45, 2.4), (5.40, 0.22, 3.6),
                                         (8.93, 0.12, 5.2), (13.3, 0.06, 7.0)]):
        f = f0 * mult * (1 + rng.uniform(-0.004, 0.004))
        s += np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) * amp * np.exp(-t * dec)
    # 敲击瞬态
    s[:int(0.006 * SR)] += rng.normal(0, 0.5, int(0.006 * SR)) * np.linspace(1, 0, int(0.006 * SR))
    return s * 0.35


def make_sword_ring(dur=1.6, seed=5):
    t = _t(dur)
    rng = _rng(seed)
    s = np.zeros(len(t))
    for mult, amp, dec in [(1, 1, 5.5), (2.4, 0.5, 7), (4.1, 0.3, 9), (6.7, 0.16, 12)]:
        s += np.sin(2 * np.pi * 2350 * mult * t) * amp * np.exp(-t * dec)
    s += highpass_fast(rng.normal(0, 1, len(t)), 4000) * np.exp(-t * 30) * 0.5
    return s * 0.22


def make_impact(dur=1.4, f0=78, seed=6):
    t = _t(dur)
    rng = _rng(seed)
    # 低频击体（带音高下坠）
    f = f0 * np.exp(-t * 5) + 32
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 4.2) * 1.0
    click = highpass_fast(rng.normal(0, 1, len(t)), 2500) * np.exp(-t * 40) * 0.55
    mid = bandpass_fast(rng.normal(0, 1, len(t)), 300, 2600) * np.exp(-t * 14) * 0.35
    return (body + click + mid) * 0.55


def make_thunder(dur=4.2, seed=7):
    rng = _rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    x = lowpass_fast(rng.normal(0, 1, n), 260) * (np.exp(-t * 0.6) * 1.4 + 0.15)
    crack = highpass_fast(rng.normal(0, 1, n), 1800) * np.exp(-t * 9) * 0.35
    return (x + crack) * 0.5


def make_riser(dur=2.2, seed=8):
    rng = _rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    k = t / dur
    noise = rng.normal(0, 1, n)
    # 上升带通（用逐段处理近似扫频）
    segs = 12
    out = np.zeros(n)
    for i in range(segs):
        a, b = int(n * i / segs), int(n * (i + 1) / segs)
        lo = 200 * (1 + 9 * i / segs)
        out[a:b] = bandpass_fast(noise[a:b], lo, lo * 3) * (i / segs) ** 1.3
    out *= np.linspace(0.1, 1, n) ** 1.5
    out += np.sin(2 * np.pi * np.cumsum(np.linspace(120, 900, n)) / SR) * np.linspace(0, 0.25, n) ** 2
    return out * 0.4


def make_ice(dur=1.8, seed=9):
    rng = _rng(seed)
    n = int(SR * dur)
    out = np.zeros(n)
    for _ in range(90):
        at = int(rng.uniform(0, dur * 0.75) ** 1.4 * SR)
        ln = int(rng.uniform(0.03, 0.25) * SR)
        ln = min(ln, n - at)
        if ln <= 8:
            continue
        t = np.arange(ln) / SR
        f = rng.uniform(1800, 9000)
        s = np.sin(2 * np.pi * f * t) * np.exp(-t * rng.uniform(18, 70))
        s += rng.normal(0, 0.4, ln) * np.exp(-t * 120)
        out[at:at + ln] += s * rng.uniform(0.12, 0.5)
    rumble = np.sin(2 * np.pi * 44 * np.arange(n) / SR) * np.exp(-np.arange(n) / SR * 2.2) * 0.5
    return (out + rumble) * 0.4


def make_tear(dur=1.6, seed=10):
    rng = _rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    noise = rng.normal(0, 1, n)
    scrape = bandpass_fast(noise, 900, 5200)
    mod = (0.4 + 0.6 * np.abs(np.sin(2 * np.pi * 18 * t))) * np.exp(-t * 2.2)
    sub = np.sin(2 * np.pi * 33 * t) * np.exp(-t * 3) * 0.9
    return (scrape * mod * 0.45 + sub) * 0.55


def make_heartbeat(dur=2.4, bpm=72):
    n = int(SR * dur)
    out = np.zeros(n)
    period = 60 / bpm
    for i in range(int(dur / period) + 1):
        at = i * period
        for k, (g, f) in enumerate([(1.0, 58), (0.6, 46)]):
            d = 0.22
            t = _t(d)
            s = np.sin(2 * np.pi * f * t) * np.exp(-t * 14) * g
            a = int((at + k * 0.26) * SR)
            if a + len(s) < n:
                out[a:a + len(s)] += s
    return out * 0.55


def make_tinnitus(dur, f=6100, gain=0.05):
    n = int(SR * dur)
    t = np.arange(n) / SR
    e = np.minimum(1, t / 0.8) * np.minimum(1, (dur - t) / 1.2)
    return (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 1.5 * t)) * e * gain


# ---------------------------------------------------------------- 混响（FFT 卷积）
def reverb(stereo, decay=2.4, wet=0.30, seed=11):
    rng = _rng(seed)
    n_ir = int(SR * decay)
    t = np.arange(n_ir) / SR
    ir = np.zeros((2, n_ir))
    for ch in range(2):
        n = rng.normal(0, 1, n_ir) * np.exp(-t * (3.2 / decay))
        n = lowpass_fast(n, 5200)
        n[:int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
        n /= np.sqrt((n ** 2).sum() + 1e-9)
        ir[ch] = n
    out = np.empty_like(stereo)
    L = stereo.shape[1]
    nfft = 1 << int(np.ceil(np.log2(L + n_ir)))
    for ch in range(2):
        wetsig = np.fft.irfft(np.fft.rfft(stereo[ch], nfft) * np.fft.rfft(ir[ch], nfft), nfft)[:L]
        out[ch] = stereo[ch] * (1 - wet) + wetsig * wet * 1.6
    return out


# ---------------------------------------------------------------- 编曲
def build(dur=DUR):
    buf = np.zeros((2, N))
    music = np.zeros((2, N))
    sfx = np.zeros((2, N))

    # 1) 底噪层：雨 + 风（从头到尾，不中断）
    rain = make_rain()
    wind = make_wind()
    for ch in range(2):
        rr = np.roll(rain, ch * 977)
        ww = np.roll(wind, ch * 613)
        sfx[ch] += rr * 0.55 + ww * 0.22

    # 2) drone（低频铺底，结尾涌起）
    dr = make_drone()
    for ch in range(2):
        sfx[ch] += dr * (1.0 if ch == 0 else 0.97)

    # 3) 弦乐 pad：Dm → Bb → Gm → A（每个切点换和弦）
    D3, F3, A3, Bb2, C4, E3, G3 = 146.83, 174.61, 220.0, 116.54, 261.63, 164.81, 196.0
    chords = [
        (3.0, 9.4, [D3, F3, A3]),
        (9.4, 15.6, [Bb2, D3, F3]),
        (15.6, 19.4, [G3 / 2, Bb2, D3]),
        (19.4, 23.6, [A3 / 4, C4 / 2, E3 / 2]),
        (23.6, 28.0, [D3, A3, F3 * 1.0]),
        (28.0, 33.2, [Bb2 / 2, D3 / 2, F3 / 2]),
        (33.2, 38.6, [D3 / 2, A3 / 4, F3 / 2]),
    ]
    pad = make_pad(chords)
    for ch in range(2):
        music[ch] += pad * (0.9 if ch == 0 else 0.86)

    # 4) 金铃（玄罗主题动机：D5-A5-F5）
    # 参考片的听觉签名就是这个铃：必须压过雨声、且以同样的三音动机反复出现。
    # 旧版 0.55 增益被雨声盖住，等于没有签名。
    BELL = [(3.12, 587.3, -0.4), (3.85, 880.0, 0.25), (4.62, 698.5, 0.4),
            (12.60, 587.3, -0.3), (13.35, 880.0, 0.15), (14.10, 698.5, 0.35),
            (20.25, 880.0, 0.30), (22.60, 587.3, -0.25), (23.40, 698.5, 0.2),
            (35.20, 587.3, 0.0), (35.95, 880.0, -0.2), (36.70, 698.5, 0.1)]
    for i, (at, f0, pan) in enumerate(BELL):
        # 签名动机用更高增益 + 稍长短的衰减，保证在雨里能被听见
        place(sfx, make_bell(f0, 2.2, seed=40 + i), at, 1.15, pan)

    # 5) 剪辑点重音（对齐分镜切点）
    hits = [15.6, 17.0, 18.2, 19.4, 21.4, 23.6, 24.8, 26.2, 33.0]
    for i, at in enumerate(hits):
        place(sfx, make_impact(1.0, f0=90 if i % 2 else 72, seed=60 + i), at, 0.42, 0.0)

    # 6) 雷（7.6s 两次）
    place(sfx, make_thunder(4.6, 71), 7.55, 0.62, -0.2)
    place(sfx, make_thunder(3.0, 72), 8.10, 0.34, 0.3)

    # 7) 心跳（对峙 / 受创）
    for at in (9.4, 21.2, 31.0):
        place(sfx, make_heartbeat(2.2), at, 0.30, 0.0)

    # 8) 耳鸣（凝视段 + 魔神登场）
    place(sfx, make_tinnitus(2.4, 6100, 0.037), 10.6, 1.0, -0.15)
    place(sfx, make_tinnitus(3.0, 5200, 0.030), 33.4, 1.0, 0.1)

    # 9) 剑鸣（白衣人入场 + 出剑）
    place(sfx, make_sword_ring(1.8, 81), 15.62, 0.55, -0.35)
    for at, g in [(18.15, 0.9), (21.35, 0.75), (26.15, 0.8)]:
        place(sfx, make_sword_ring(1.6, 82), at, g, 0.35)

    # 10) Rising（大招前）
    place(sfx, make_riser(2.4, 91), 23.6, 0.55, 0.0)

    # 11) 冰晶爆发 + 白闪
    place(sfx, make_ice(2.0, 92), 24.75, 0.85, 0.0)

    # 12) 空间撕裂 + 魔神登场
    place(sfx, make_tear(1.8, 93), 29.30, 0.95, 0.0)
    place(sfx, make_tear(2.2, 94), 33.00, 0.55, -0.25)

    # 13) 动作：15.6 前 0.3s 抽空（参考片的"骤停"手法）
    for ch in range(2):
        buf[ch] = music[ch] + sfx[ch]
    gate = np.ones(N)
    for (a, b) in [(15.42, 15.72), (27.92, 28.18), (38.55, 40.0)]:
        i0, i1 = int(a * SR), int(b * SR)
        k = np.linspace(1, 0.06, i1 - i0)
        gate[i0:i1] = np.minimum(gate[i0:i1], k if a < 20 else np.linspace(0.06, 1, i1 - i0))
    buf *= gate

    # 14) 混响 + 母带
    buf = reverb(buf, decay=2.2, wet=0.22)
    # 高频搁架：参考片频谱重心 ≈3.2kHz，本片此前 4.3kHz（偏亮、易疲劳）
    for ch in range(2):
        b = buf[ch]
        buf[ch] = b - 0.34 * lowpass_fast(b, 3200) + 0.34 * lowpass_fast(b, 3200) * 0.0 \
            if False else (0.66 * b) + 0.34 * lowpass_fast(b, 3400)
        buf[ch] = lowpass_fast(buf[ch], 15000)
    # 动态压缩（软膝 + tanh）
    rms = np.sqrt((buf ** 2).mean())
    buf *= 0.145 / (rms + 1e-9)
    buf = np.tanh(buf * 1.18) * 0.92
    # 首尾淡入淡出
    fi, fo = int(0.8 * SR), int(1.2 * SR)
    buf[:, :fi] *= np.linspace(0, 1, fi) ** 0.6
    buf[:, -fo:] *= np.linspace(1, 0, fo) ** 1.5
    peak = np.abs(buf).max()
    buf = buf / (peak + 1e-9) * 0.89          # ≈ -1 dBFS
    return buf


def write_wav(path, buf, sr=SR):
    import wave, struct
    d = (np.clip(buf.T, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(d.tobytes())


if __name__ == "__main__":
    import sys
    b = build()
    out = sys.argv[1] if len(sys.argv) > 1 else "out/score.wav"
    write_wav(out, b)
    rms = 20 * np.log10(np.sqrt((b ** 2).mean()) + 1e-9)
    print(f"written {out}  dur={b.shape[1]/SR:.2f}s  RMS={rms:.1f}dBFS  peak={20*np.log10(np.abs(b).max()):.1f}dBFS")
