#!/usr/bin/env python3
"""评审子代理 (Review Agent) —— 独立给成片打分，参考片作为基准。

设计原则
  1. **独立性**：指标代码与渲染端完全分离，不 import render/*，不复用 scripts/qc.py。
  2. **量表驱动**：权重/阈值全部来自 review/rubric.json，改量表即改结论。
  3. **可解释**：每个维度给出分数 + 实测值 + 参考值 + 自动生成的扣分原因与修改建议。
  4. **人机分工**：量化维度由子代理算；主观维度（角色/构图/钩子）由视觉评审填写
     review/visual_scores.json，子代理负责合并与加权。

用法
  python3 scripts/reviewer.py                       # 自动部分 + 合并已有视觉分
  python3 scripts/reviewer.py --side-by-side        # 额外产出参考/成片并排对照图
产出
  out/review/report.json      机器可读评分
  docs/07-评审报告.md          人类可读报告
  out/review/side_*.jpg       并排对照图（可选）
"""
import os, sys, json, subprocess, tempfile, wave, argparse, math
import numpy as np
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = imageio_ffmpeg.get_ffmpeg_exe()
FONT = os.path.join(ROOT, "assets", "fonts", "Title-Serif.otf")
RUBRIC = os.path.join(ROOT, "review", "rubric.json")
VISUAL = os.path.join(ROOT, "review", "visual_scores.json")
OUTDIR = os.path.join(ROOT, "out", "review")


# ============================================================ 版本绑定
def cut_fingerprint(path):
    """成片指纹：时长 + 字节数 + 前 2MB 的哈希。

    主观分必须绑定到具体的成片版本，否则重渲后旧分会被静默复用 ——
    那是最隐蔽的一种"自评通胀"。
    """
    import hashlib
    st = os.stat(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(2 * 1024 * 1024))
    dur = 0.0
    out = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    for tok in out.split():
        if tok.startswith("Duration:"):
            continue
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return "%s_%d_%.1fs" % (h.hexdigest()[:12], st.st_size, dur)


# ============================================================ 基础探测
def probe(path):
    p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
    t = p.stderr
    d = {"raw": t}
    for line in t.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            d["duration"] = int(h) * 3600 + int(m) * 60 + float(s)
        if "Video:" in line:
            parts = [x.strip() for x in line.split(",")]
            for x in parts:
                if "x" in x and x.split("x")[0].isdigit() and x.split("x")[1][:4].isdigit():
                    d["w"], d["h"] = int(x.split("x")[0]), int(x.split("x")[1][:4])
                if x.endswith("fps") and x[:-3].replace(".", "").isdigit():
                    d["fps"] = float(x[:-3])
                if x in ("h264", "hevc", "vp9", "av1"):
                    d["vcodec"] = x
        if "Audio:" in line:
            parts = [x.strip() for x in line.split(",")]
            d["audio_ch"] = 2 if "stereo" in line else (1 if "mono" in line else None)
            for x in parts:
                if x in ("aac", "mp3", "opus"):
                    d["acodec"] = x
    if "bitrate:" in t:
        for line in t.splitlines():
            if "bitrate:" in line:
                try:
                    d["bitrate_kbps"] = float(line.split("bitrate:")[1].split("kb/s")[0].strip())
                except Exception:
                    pass
    return d


# ============================================================ 逐帧采样
def frames(path, w=320, h=180, fps=10):
    raw = tempfile.mktemp(suffix=".raw")
    subprocess.run([FF, "-v", "error", "-i", path, "-vf", f"scale={w}:{h},fps={fps}",
                    "-pix_fmt", "rgb24", "-f", "rawvideo", raw, "-y"], capture_output=True)
    a = np.fromfile(raw, dtype=np.uint8)
    os.remove(raw)
    n = a.size // (w * h * 3)
    return a[: n * w * h * 3].reshape(n, h, w, 3).astype(np.float32), fps


def frames_full(path, w=640, h=360, step=15):
    """用于锐度/噪点：每 step 帧取一帧，省算力。"""
    raw = tempfile.mktemp(suffix=".raw")
    subprocess.run([FF, "-v", "error", "-i", path, "-vf",
                    f"select='not(mod(n\\,{step}))',scale={w}:{h}",
                    "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", raw, "-y"],
                   capture_output=True)
    a = np.fromfile(raw, dtype=np.uint8)
    os.remove(raw)
    n = a.size // (w * h * 3)
    return a[: n * w * h * 3].reshape(n, h, w, 3).astype(np.float32)


# ============================================================ 各维度指标
def scene_cuts(path, th=0.30):
    p = subprocess.run([FF, "-hide_banner", "-i", path, "-vf",
                        f"select='gt(scene,{th})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(t.split(":")[1]) for t in p.stderr.split() if t.startswith("pts_time:")]


def tone_metrics(x):
    lum = x.mean(3)
    sat = (x.max(3) - x.min(3))
    teal = (x[..., 1] + x[..., 2] - 2 * x[..., 0]).mean()
    gold = (x[..., 0] + x[..., 1] - 2 * x[..., 2]).mean()
    return dict(
        luma_mean=float(lum.mean()),
        luma_p5=float(np.percentile(lum, 5)),
        luma_p95=float(np.percentile(lum, 95)),
        luma_std=float(lum.std()),
        sat=float(sat.mean()),
        teal=float(teal),
        gold=float(gold),
        hi_clip=float((lum > 250).mean()),
        lo_clip=float((lum < 8).mean()),
        lowkey_ratio=float((lum < 0.25 * 255).mean()),
    )


def quality_metrics(xf):
    """锐度（拉普拉斯方差）、噪点（平坦区高频残差）、闪烁、黑边"""
    sharp, noise = [], []
    for fr in xf:
        g = fr.mean(2)
        lap = (np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]))
        sharp.append(float(lap.var()))
        # 局部梯度小 → 视为平坦区，取高频残差作噪声估计
        gp = np.abs(np.diff(g, axis=0))[:, :-1] + np.abs(np.diff(g, axis=1))[:-1, :]
        flat = gp < 3.0
        box = g[:-1, :-1]
        hp = np.abs(box - (box.mean() if flat.size == 0 else box.mean()))
        if flat.sum() > 200:
            noise.append(float(hp[flat].mean()))
    return dict(sharpness=float(np.mean(sharp)), noise=float(np.mean(noise) if noise else 0.0),
                samples=len(xf))


def motion_metrics(x):
    """把"动"拆成全局位移与主体局部运动。

    静帧 + 推拉：全局位移大、局部≈0 → 观感像 PPT。
    真动作：配准掉相机运动后仍有明显残差 → 主体在自己动。
    使用相位相关（FFT）估帧间整体平移，再用整数平移配准求残差中位数。
    """
    g = x.mean(3)                                  # (n,h,w) 灰度
    n, h, w = g.shape
    if n < 4:
        return dict(global_px=0.0, local_px=0.0, purity=0.0)
    win = np.outer(np.hanning(h), np.hanning(w))
    gs, ls = [], []
    for i in range(n - 1):
        a, b = g[i] - g[i].mean(), g[i + 1] - g[i + 1].mean()
        R = np.fft.rfft2(a * win) * np.conj(np.fft.rfft2(b * win))
        R /= (np.abs(R) + 1e-9)
        c = np.fft.irfft2(R, s=(h, w))
        py, px = np.unravel_index(np.argmax(c), c.shape)
        dy = py - h if py > h // 2 else py
        dx = px - w if px > w // 2 else px
        gs.append(float(np.hypot(dx, dy)))
        reg = np.roll(np.roll(g[i], -dy, 0), -dx, 1)   # 配准掉全局位移
        r = np.abs(g[i + 1] - reg)
        ls.append(float(np.median(r[r > np.percentile(r, 60)])))
    gmed, lmed = float(np.median(gs)), float(np.median(ls))
    return dict(global_px=round(gmed, 2), local_px=round(lmed, 2),
                purity=round(lmed / max(0.6, gmed), 2))


def flicker_metric(x):
    m = x.mean(axis=(1, 2, 3))
    d = np.abs(np.diff(m))
    return float(d.std()), float(np.percentile(d, 99))


def border_metric(path):
    x, _ = frames(path, 320, 180, 5)
    lum = x.mean(3).mean(2)
    row = lum.mean(1)
    col = lum.mean(0)
    top = next((i for i, v in enumerate(row) if v > 3), len(row))
    bot = next((i for i, v in enumerate(row[::-1]) if v > 3), len(row))
    left = next((i for i, v in enumerate(col) if v > 3), len(col))
    right = next((i for i, v in enumerate(col[::-1]) if v > 3), len(col))
    return int(min(top, bot, left, right))


def audio_metrics(path):
    wav = tempfile.mktemp(suffix=".wav")
    subprocess.run([FF, "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", "44100", wav, "-y"],
                   capture_output=True)
    if not os.path.exists(wav):
        return None
    w = wave.open(wav)
    sr, nch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    w.close()
    os.remove(wav)
    if x.size == 0:
        return None
    mono = x.reshape(-1, nch).mean(1)
    rms = float(np.sqrt((mono ** 2).mean()))
    peak = float(np.abs(mono).max())
    # 频谱重心 / 平坦度
    seg = mono[: sr * 6]
    S = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / sr)
    centroid = float((S * f).sum() / (S.sum() + 1e-9))
    ps = S ** 2 + 1e-12
    flatness = float(np.exp(np.log(ps).mean()) / ps.mean())
    # 起音检测（10ms 包络 + 6dB 跳变）
    hop = int(sr * 0.01)
    env = np.array([np.sqrt((mono[i:i + hop] ** 2).mean() + 1e-12)
                    for i in range(0, len(mono) - hop, hop)])
    db = 20 * np.log10(env + 1e-9)
    d = np.diff(db)
    onsets = []
    for i in np.where(d > 6)[0]:
        t = i * 0.01
        if not onsets or t - onsets[-1] > 0.25:
            onsets.append(float(t))
    return dict(rms_db=20 * math.log10(rms + 1e-9),
                peak_db=20 * math.log10(peak + 1e-9),
                crest_db=20 * math.log10(peak / (rms + 1e-9)),
                centroid_khz=centroid / 1000.0, flatness=flatness,
                onsets=onsets, duration=len(mono) / sr, channels=nch)


def rhythm_metrics(cuts, dur):
    bins = np.arange(0, math.ceil(dur) + 2, 2.0)
    hist, _ = np.histogram(cuts, bins=bins)
    intro = sum(1 for c in cuts if c < 16.0)
    mid = sum(1 for c in cuts if 16.0 <= c < 28.0)
    tail = sum(1 for c in cuts if c >= 28.0)
    return dict(cut_count=len(cuts), asl=dur / max(1, len(cuts)),
                hist=hist.tolist(), intro_cuts=intro, mid_cuts=mid, tail_cuts=tail)


def onset_hit_rate(am, cuts):
    if not am or not am["onsets"] or not cuts:
        return 0.0
    on = np.array(am["onsets"])
    hit = sum(1 for c in cuts if np.min(np.abs(on - c)) <= 0.20)
    return hit / len(cuts)


# ============================================================ 逐镜体检（成片）
def per_shot_scan(path, shots):
    """对每个镜头区间抽样，找过曝/欠曝/锐度异常，返回最差项。"""
    rows = []
    for s in shots:
        t0, t1 = s["t0"], s["t1"]
        mid = (t0 + t1) / 2
        raw = tempfile.mktemp(suffix=".raw")
        subprocess.run([FF, "-v", "error", "-ss", f"{max(0, mid - 0.15):.2f}", "-t", "0.4",
                        "-i", path, "-vf", "scale=320:180", "-pix_fmt", "rgb24",
                        "-f", "rawvideo", raw, "-y"], capture_output=True)
        if not os.path.exists(raw):
            continue
        a = np.fromfile(raw, dtype=np.uint8)
        os.remove(raw)
        if a.size < 320 * 180 * 3:
            continue
        x = a[: (a.size // (320 * 180 * 3)) * 320 * 180 * 3].reshape(-1, 180, 320, 3).astype(np.float32)
        lum = x.mean(3)
        hi = float((lum > 250).mean())
        g = x[..., :3].mean(3)
        lap = np.abs(4 * g[:, 1:-1, 1:-1] - g[:, :-2, 1:-1] - g[:, 2:, 1:-1]
                     - g[:, 1:-1, :-2] - g[:, 1:-1, 2:]).var()
        rows.append(dict(id=s["id"], art=s.get("art", ""), t0=t0, t1=t1,
                         hi_clip=hi, luma=float(lum.mean()), sharp=float(lap)))
    worst_exp = max((r["hi_clip"] for r in rows), default=0.0)
    worst_row = max(rows, key=lambda r: r["hi_clip"]) if rows else None
    return rows, worst_exp, worst_row


# ============================================================ 打分
def sim_score(value, ref, tol):
    if value is None or ref is None:
        return 0.0
    return float(100 * math.exp(-abs(value - ref) / tol))


def band_score(value, lo, hi, hard_lo, hard_hi):
    if value is None:
        return 0.0
    if lo <= value <= hi:
        return 100.0
    if value < lo:
        if hard_lo is not None and hard_lo > -1 and value <= hard_lo:
            return 0.0
        span = (lo - hard_lo) if (hard_lo is not None and hard_lo > -1) else (abs(lo) + 1e-6)
        return float(np.clip(100 * (1 - (lo - value) / max(span, 1e-6)), 0, 100))
    span = (hard_hi - hi) if (hard_hi is not None and hard_hi > hi) else (abs(hi) + 1e-6)
    return float(np.clip(100 * (1 - (value - hi) / max(span, 1e-6)), 0, 100))


def grade_of(score):
    if score >= 90: return "S"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    return "D"


def evaluate(cand_path, ref_path, side_by_side=False):
    rub = json.load(open(RUBRIC, encoding="utf-8"))
    visual = json.load(open(VISUAL, encoding="utf-8")) if os.path.exists(VISUAL) else {}
    # 主观分是否针对当前这一版成片
    fp = cut_fingerprint(cand_path)
    vcut = visual.get("_cut")
    visual_fresh = (vcut == fp)
    if not visual_fresh:
        why = ("未绑定版本（旧格式）" if not vcut
               else "绑定的是另一版成片 %s" % vcut)
        print("⚠️ 主观分%s，本次不予采用 → 请对该版重新打分并写入 _cut=%s" % (why, fp))
        visual = {k: v for k, v in visual.items() if k.startswith("_")}
    shots_cfg = json.load(open(os.path.join(ROOT, "shots", "shots.json")))["shots"]

    pc, pr = probe(cand_path), probe(ref_path)
    xc, fpsc = frames(cand_path)
    xr, fpsr = frames(ref_path)
    fc = frames_full(cand_path)
    fr_ = frames_full(ref_path)
    cuts_c, cuts_r = scene_cuts(cand_path), scene_cuts(ref_path)
    ac, ar = audio_metrics(cand_path), audio_metrics(ref_path)

    mc = tone_metrics(xc)
    mr = tone_metrics(xr)
    qc = quality_metrics(fc)
    qr = quality_metrics(fr_)
    fl_c, fl99_c = flicker_metric(xc)
    fl_r, fl99_r = flicker_metric(xr)
    bc = border_metric(cand_path)
    mo_c, mo_r = motion_metrics(xc), motion_metrics(xr)
    rh_c = rhythm_metrics(cuts_c, pc.get("duration", 0))
    rh_r = rhythm_metrics(cuts_r, pr.get("duration", 0))

    # 节奏曲线相关性：把全片按百分比切成 10 段，比较"切点密度曲线"
    # （不按绝对时间对齐，避免因镜头长度不同而误判剪辑选择）
    def density(cuts, dur, k=10):
        if not cuts or dur <= 0:
            return np.zeros(k)
        idx = np.clip((np.array(cuts) / dur * k).astype(int), 0, k - 1)
        h = np.bincount(idx, minlength=k).astype(float)
        return h / (h.sum() + 1e-9)
    dc, dr = density(cuts_c, pc.get("duration", 1)), density(cuts_r, pr.get("duration", 1))
    corr = float(np.corrcoef(dc, dr)[0, 1]) if dc.std() > 0 and dr.std() > 0 else 0.0

    rows, worst_exp, worst_row = per_shot_scan(cand_path, shots_cfg)

    M = {
        "duration": pc.get("duration"),
        "resolution_ok": 1.0 if (pc.get("w"), pc.get("h")) == (pr.get("w"), pr.get("h")) else 0.0,
        "audio_ok": 1.0 if (pc.get("audio_ch") == 2 and ac) else 0.0,
        "luma_mean": mc["luma_mean"], "luma_p5": mc["luma_p5"], "luma_p95": mc["luma_p95"],
        "sat": mc["sat"], "teal": mc["teal"], "gold": mc["gold"],
        "hi_clip": mc["hi_clip"], "lo_clip": mc["lo_clip"],
        "cut_count": rh_c["cut_count"], "asl": rh_c["asl"],
        "rhythm_corr": (corr + 1) / 2, "intro_cuts": rh_c["intro_cuts"],
        "sharpness_rel": qc["sharpness"] / max(1e-6, qr["sharpness"]),
        "noise_rel": qc["noise"] / max(1e-6, qr["noise"]),
        "flicker_rel": fl_c / max(1e-6, fl_r),
        "border_px": float(bc),
        "worst_shot_exp": worst_exp,
        "subject_motion": mo_c["local_px"], "motion_purity": mo_c["purity"],
        "motion_global": mo_c["global_px"],
        "rms_db": ac["rms_db"] if ac else None,
        "peak_db": ac["peak_db"] if ac else None,
        "crest_db": ac["crest_db"] if ac else None,
        "centroid_khz": ac["centroid_khz"] if ac else None,
        "onset_hit": onset_hit_rate(ac, cuts_c),
    }
    R = {
        "luma_mean": mr["luma_mean"], "luma_p5": mr["luma_p5"], "luma_p95": mr["luma_p95"],
        "sat": mr["sat"], "teal": mr["teal"], "gold": mr["gold"],
        "hi_clip": mr["hi_clip"], "lo_clip": mr["lo_clip"],
        "cut_count": rh_r["cut_count"], "asl": rh_r["asl"], "intro_cuts": rh_r["intro_cuts"],
        "subject_motion": mo_r["local_px"], "motion_purity": mo_r["purity"],
        "rms_db": ar["rms_db"] if ar else None, "peak_db": ar["peak_db"] if ar else None,
        "crest_db": ar["crest_db"] if ar else None, "centroid_khz": ar["centroid_khz"] if ar else None,
    }

    # ---- 打分 ----
    dim_results = []
    for dim in rub["dimensions"]:
        items = []
        for it in dim["items"]:
            k = it["kind"]
            m = it["metric"]
            val = M.get(m)
            ref = R.get(m)
            if k == "manual":
                raw = visual.get(m)
                score = float(raw) if isinstance(raw, (int, float)) else None
            elif k == "similarity":
                score = sim_score(val, ref, it["tol"])
            elif k == "band":
                score = band_score(val, it["lo"], it["hi"], it.get("hard_lo"), it.get("hard_hi"))
            elif k == "target":
                score = 100.0 if (val is not None and val >= it.get("pass", 1)) else 0.0
            elif k == "max":                      # 越小越好（如黑边像素）
                lim = it.get("pass", 0.0)
                score = 100.0 if (val is not None and val <= lim) else 0.0
            else:
                score = None
            items.append(dict(metric=m, name=it["name"], kind=k, value=val, ref=ref, score=score))
        known = [i["score"] for i in items if i["score"] is not None]
        dim_score = float(np.mean(known)) if known else None
        dim_results.append(dict(key=dim["key"], name=dim["name"], weight=dim["weight"],
                                score=dim_score, items=items,
                                pending=sum(1 for i in items if i["score"] is None)))

    total_w = sum(d["weight"] for d in dim_results if d["score"] is not None)
    total = (sum(d["score"] * d["weight"] for d in dim_results if d["score"] is not None)
             / total_w) if total_w else 0.0

    # ---- 自动发现问题 ----
    findings = []
    def add(sev, area, msg, fix):
        findings.append(dict(severity=sev, area=area, issue=msg, fix=fix))

    # 指标 → 可执行的动作（方向由实测值与参考值的关系决定）
    FIX = {
        "subject_motion": ("动作镜主体位移不足。检查该镜 key_chain 是否覆盖足够的总位移，"
                           "并确认 key_skip_canvas 已启用（否则开头会倒放）。"),
        "motion_purity": ("局部/全局比偏低 = 整幅都在平移。把位移收回到环境层（sky/gnd），"
                          "主体所在中段保持刚性。"),
        "worst_shot_exp": "在 shots.json 给该镜调低 exp，或减小 flash_power。",
        "rhythm_corr": "切点分布与参考片不符：按参考片的分段切点密度重排 shots.json 的 t1。",
        "sharpness_rel": "画面偏软：检查该镜 zoom 是否长期 >1.15（过度放大导致插值变软）。",
        "noise_rel": "颗粒偏重：调低 render_video.py 的 GRADE['grain']（当前 1.5）。",
        "flicker_rel": "亮度闪烁：检查闪光/白闪层的时间衰减是否过陡。",
        "onset_hit": "音效与切点未对齐：把 scripts 里的音效起音点对齐 shots.json 的 t0。",
        "crest_db": "动态范围偏窄：检查混音是否被限幅器压平。",
        "centroid_khz": "频谱重心偏移：调整雨声/低频的比例。",
        "hi_clip": "高光溢出：调低 bloom_gain 或该镜 exp。",
        "lo_clip": "死黑过多：调高 GRADE['lift']。",
    }

    def direction(i):
        """给出"该往哪边调"，而不是笼统的"按偏差方向调参"。"""
        v, r = i["value"], i["ref"]
        if v is None or r is None:
            return ""
        if i["kind"] == "similarity":
            return "偏低，需上调" if v < r else "偏高，需下调"
        if i["kind"] == "band":
            lo, hi = i.get("lo"), i.get("hi")
            if lo is not None and v < lo:
                return "低于区间下限"
            if hi is not None and v > hi:
                return "高于区间上限"
        return ""

    for d in dim_results:
        for i in d["items"]:
            if i["score"] is None or i["score"] >= 82:
                continue
            sev = "高" if i["score"] < 55 else ("中" if i["score"] < 70 else "低")
            if i["kind"] == "manual":
                # 人工项没有实测值，扣分原因以评审意见原文为准，不再编造 "= None"
                note = (visual.get("_comments") or {}).get(i["name"], "")
                add(sev, d["name"],
                    f"{i['name']} 主观评分 {i['score']:.0f}/100" + (f"：{note}" if note else ""),
                    "见第四节视觉评审意见，按其中列出的具体镜头修改。")
                continue
            val = i["value"] if not isinstance(i["value"], float) else round(i["value"], 2)
            ref = i["ref"] if not isinstance(i["ref"], float) else (
                round(i["ref"], 2) if i["ref"] is not None else "-")
            dirn = direction(i)
            add(sev, d["name"],
                f"{i['name']} = {val}（参考 {ref}）" + (f"，{dirn}" if dirn else ""),
                FIX.get(i["metric"], "见 docs/04 质检报告中的同口径数值，按偏差方向调参。"))

    if worst_row and worst_row["hi_clip"] > 0.05:
        add("中", "画面质量", f"镜 {worst_row['id']}（{worst_row['art']}）高光溢出 {worst_row['hi_clip']*100:.1f}%",
            "该镜原图偏亮，调低 exp 或改用 vfx 关闭强闪光层")

    if side_by_side:
        make_side_by_side(cand_path, ref_path, pc.get("duration", 40))

    report = dict(
        rubric=rub["_meta"]["name"],
        candidate=os.path.basename(cand_path), reference=os.path.basename(ref_path),
        total=round(total, 1), grade=grade_of(total),
        dimensions=[{k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()
                     if k != "items"} for d in dim_results],
        items=[{kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in i.items()}
               for d in dim_results for i in d["items"]],
        metrics=M, reference_metrics=R,
        per_shot=rows, findings=findings,
        probe=dict(candidate=pc.get("raw", ""), reference_duration=pr.get("duration")),
        visual_comments=visual.get("_comments", {}),
        pending_manual=sum(d["pending"] for d in dim_results),
    )
    return report


# ============================================================ 并排对照图
def semantic_pairs():
    """按叙事功能配对（成片镜 ↔ 参考片同功能时间点）。

    参考片的时间轴依据 docs/00 的逐镜读图，不是按"绝对秒数"硬对齐 ——
    否则会拿"伞下全景"去比"半脸特写"，得出错误的构图结论。
    """
    return [
        ("赤足踏水", 1.2, 1.0),
        ("箓雾缠足", 4.2, 3.2),
        ("伞下人物", 6.4, 5.0),
        ("伞面特写", 8.4, 6.6),
        ("半脸凝视", 11.6, 7.8),
        ("竖瞳", 14.2, 10.0),
        ("远塔天象", 10.2, 12.0),
        ("白衣入场", 16.2, 17.0),
        ("对峙", 17.6, 19.0),
        ("冲刺", 18.8, 20.4),
        ("兵器相撞", 19.8, 21.0),
        ("成盾", 20.8, 23.0),
        ("剑气横扫", 21.8, 21.5),
        ("胸口侵蚀", 23.0, 25.0),
        ("跃起穿柱", 24.2, 27.0),
        ("冰阵爆发", 25.4, 29.5),
        ("光球对撞", 27.0, 32.0),
        ("白闪余波", 28.3, 33.5),
        ("空间裂缝", 30.2, 35.0),
        ("魔神登场", 32.0, 36.5),
        ("巨手压地", 33.8, 38.0),
        ("金色竖瞳", 35.2, 38.6),
        ("片名收尾", 38.2, 38.9),
    ]


def make_side_by_side(cand, ref, dur, pairs=None):
    """pairs: [(标签, 成片时间, 参考时间)] —— 语义对齐对比。"""
    os.makedirs(OUTDIR, exist_ok=True)
    if pairs is None:
        pairs = semantic_pairs()
    pairs = [(lb, a, b) for lb, a, b in pairs if a < dur and b < min(39.0, dur + 5)]

    def grab(path, t, w=560, h=315):
        raw = tempfile.mktemp(suffix=".raw")
        subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale={w}:{h}", "-pix_fmt", "rgb24", "-f", "rawvideo", raw, "-y"],
                       capture_output=True)
        if not os.path.exists(raw):
            return None
        a = np.fromfile(raw, dtype=np.uint8)
        os.remove(raw)
        if a.size < w * h * 3:
            return None
        return Image.fromarray(a[: w * h * 3].reshape(h, w, 3))

    try:
        font = ImageFont.truetype(FONT, 16)
    except Exception:
        font = ImageFont.load_default()
    made = 0
    for grp in range(0, len(pairs), 4):
        chunk = pairs[grp:grp + 4]
        rows = []
        for lb, ta, tb in chunk:
            a, b = grab(cand, ta), grab(ref, tb)
            if a is None or b is None:
                continue
            rows.append((lb, ta, tb, a, b))
        if not rows:
            continue
        tw, th = rows[0][3].size
        pad = 6
        W = 2 * tw + 3 * pad
        H = len(rows) * (th + 24 + pad) + pad
        sheet = Image.new("RGB", (W, H), (12, 14, 18))
        d = ImageDraw.Draw(sheet)
        for i, (lb, ta, tb, a, b) in enumerate(rows):
            y = pad + i * (th + 24 + pad)
            sheet.paste(a, (pad, y + 22))
            sheet.paste(b, (pad * 2 + tw, y + 22))
            d.text((pad + 4, y + 4), f"成片 · {lb} @ {ta:.1f}s", font=font, fill=(120, 220, 210))
            d.text((pad * 2 + tw + 4, y + 4), f"参考 · 同功能 @ {tb:.1f}s", font=font,
                   fill=(220, 200, 140))
        p = os.path.join(OUTDIR, f"side_{grp//4+1}.jpg")
        sheet.save(p, quality=88, optimize=True)
        made += 1
    print(f"并排对照图 {made} 张 → {OUTDIR}")


# ============================================================ 报告
def write_report(rep):
    L = []
    g = rep["grade"]
    icon = {"S": "🏆", "A": "✅", "B": "🟡", "C": "⚠️", "D": "❌"}[g]
    L.append("# 07 · 评审报告（评审子代理产出）\n")
    L.append("> 评审者：`scripts/reviewer.py`（独立实现，不引用渲染端代码）+ 视觉评审人工分。"
             "量表：`review/rubric.json`。\n")
    L.append(f"> 被评对象：`{rep['candidate']}`　基准：`{rep['reference']}`\n")
    L.append(f"\n## 总评：{icon} **{rep['total']} / 100** · 等级 **{g}**\n")
    if rep.get("pending_manual"):
        L.append(f"> ⚠️ 还有 {rep['pending_manual']} 项主观评分未提交（`review/visual_scores.json`），"
                 "叙事维度暂不计入总分的加权。\n")

    L.append("\n## 一、维度得分\n")
    L.append("| 维度 | 权重 | 得分 | 等级 | 说明 |\n|---|---|---|---|---|")
    for d in rep["dimensions"]:
        s = d["score"]
        if s is None:
            L.append(f"| {d['name']} | {d['weight']} | 待人工 | - | 需视觉评审 |")
        else:
            L.append(f"| {d['name']} | {d['weight']} | {s:.1f} | {grade_of(s)} | |")
    L.append(f"| **加权总分** | 100 | **{rep['total']}** | **{g}** | |")

    L.append("\n## 二、逐项实测\n")
    L.append("| 维度 | 指标 | 成片 | 参考片 | 得分 |\n|---|---|---|---|---|")
    for it in rep["items"]:
        v = it["value"]
        r = it["ref"]
        fmt = lambda z: ("-" if z is None else (f"{z:.2f}" if isinstance(z, float) else str(z)))
        s = it["score"]
        L.append(f"| {it['name']} | {it['metric']} | {fmt(v)} | {fmt(r)} | "
                 f"{'待人工' if s is None else f'{s:.1f}'} |")

    L.append("\n## 三、扣分项与修改建议（自动生成）\n")
    if not rep["findings"]:
        L.append("无。\n")
    else:
        order = {"高": 0, "中": 1, "低": 2}
        for f in sorted(rep["findings"], key=lambda z: order.get(z["severity"], 3)):
            L.append(f"- **[{f['severity']}] {f['area']}**：{f['issue']}\n  - 建议：{f['fix']}")

    if rep["visual_comments"]:
        L.append("\n## 四、视觉评审意见（人工）\n")
        for k, v in rep["visual_comments"].items():
            L.append(f"- **{k}**：{v}")

    L.append("\n## 五、逐镜检查\n")
    L.append("| 镜 | 素材 | 起点 | 高光溢出 | 亮度 | 锐度 |\n|---|---|---|---|---|---|")
    for r in rep["per_shot"]:
        flag = " ⚠️" if r["hi_clip"] > 0.05 else ""
        L.append(f"| {r['id']} | {r['art']} | {r['t0']:.1f}s | {r['hi_clip']*100:.2f}%{flag} | "
                 f"{r['luma']:.0f} | {r['sharp']:.0f} |")

    L.append("\n## 六、评审方法与可信度声明\n")
    L.append("""- **量化维度**（技术/影调/节奏/画面/声音，共 85 分）由脚本从成片与参考片的像素和音频直接计算，
  同口径、可复现，换任何一条片子都能跑同一张量表。
- **主观维度**（叙事与美术一致性，15 分）由视觉评审逐张看帧打分，意见原文写在第四节。
- **已知局限**：量化指标无法判断"好不好看"。比如"帧间差"这一项，成片分数低，
  但其中一部分来自"静帧路线"的客观限制，而不是审美失误 —— 这一点写进了扣分建议里。
- 参考片只作**基准**使用，不参与任何创作判断；评审不修改成片，只出分数与建议。
""")
    p = os.path.join(ROOT, "docs", "07-评审报告.md")
    open(p, "w", encoding="utf-8").write("\n".join(L))
    print("报告 →", p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", default=os.path.join(ROOT, "out", "青冥·伞_40s.mp4"))
    ap.add_argument("--reference", default=os.path.join(ROOT, "original-720p.mp4"))
    ap.add_argument("--side-by-side", action="store_true")
    a = ap.parse_args()
    rep = evaluate(a.candidate, a.reference, a.side_by_side)
    os.makedirs(OUTDIR, exist_ok=True)
    json.dump(rep, open(os.path.join(OUTDIR, "report.json"), "w"), ensure_ascii=False, indent=1)
    write_report(rep)
    print(f"\n总评 {rep['total']} / 100  等级 {rep['grade']}")
    for d in rep["dimensions"]:
        s = d["score"]
        print(f"  {d['name']:<12} {'待人工' if s is None else f'{s:5.1f}'}  (权重 {d['weight']})")
    print(f"  扣分项 {len(rep['findings'])} 条")


if __name__ == "__main__":
    main()
