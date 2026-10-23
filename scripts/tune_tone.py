#!/usr/bin/env python3
"""影调参数搜索 v2：直接以评审量表的"影调与色彩"得分作为目标函数。

与 `scripts/tune_grade.py` 的区别：
  · 覆盖全部 23 镜（不是 8 镜），按镜头时长加权抽样 —— 平均型指标
    （亮度均值 / 饱和 / 青绿 / 金色）因此与成片实测同口径；
  · 目标函数不是自拟的 cost，而是 `review/rubric.json` 里影调维度的 8 个分项，
    用 `sim_score` 原样计算，得分可直接与 `docs/07` 对比；
  · 支持指定搜索网格，逐轮缩小。

重点解决两个"看不见的参数"：
  · `knee`：高光软膝起点。硬编码 0.78（≈199）时全片 p95 只有 184，压缩从未触发，
    历轮调 `hi_roll` 全都无效。暴露为参数后才能真的压高光。
  · `gamma`：压低膝点会连带压暗中间调，必须用 gamma 补回来，否则亮度掉分。

用法:
  python3 scripts/tune_tone.py                       # 只评当前 GRADE
  python3 scripts/tune_tone.py --grid knee,gamma,sat # 小网格搜索
  python3 scripts/tune_tone.py --grid knee,gamma,sat --apply   # 写入 render_video.py
"""
import argparse
import itertools
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from render.lib.core import Cache, W, H, np2img          # noqa: E402
from render.lib.shot import Shot                        # noqa: E402
from render.render_video import post, GRADE             # noqa: E402
from reviewer import tone_metrics, frames, sim_score, band_score  # noqa: E402

REF = os.path.join(ROOT, "original-720p.mp4")
RUB = os.path.join(ROOT, "review", "rubric.json")

# 搜索空间：默认值 = 当前 GRADE 的值
SPACE = {
    "knee":   [0.78, 0.74, 0.72, 0.70, 0.66],
    "gamma":  [0.905, 0.89, 0.875, 0.86],
    "sat":    [0.99, 1.01, 1.03, 1.05],
    "cool_r": [0.46, 0.50, 0.52, 0.54],
    "black_lift": [0.045, 0.052, 0.058, 0.064],
    "warm_hl": [0.03, 0.026, 0.022],
}
# 每个镜头抽 2 帧（25% / 60% 处），与 tune_grade.py 一致
FRACS = (0.25, 0.60)


BIAS_PATH = os.path.join(ROOT, "out", "tone_bias.json")
BIAS_KEYS = ("luma_mean", "luma_p5", "luma_p95", "sat", "teal", "gold")


def film_metrics():
    """当前成片的实测影调（评审报告口径），用于校正抽样偏差。"""
    p = os.path.join(ROOT, "out", "review", "report.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8")).get("metrics")


def load_bias():
    """抽样偏差必须是**固定常数**。

    它只能从"成片"与"用同一套 GRADE 抽样"这一对里算出来。若每轮都用"当前这一版
    抽样值 − 旧成片实测值"，那么改了 gamma 之后偏差本身会跟着变，目标值随之漂移 ——
    实测就是这样把 p5 目标从 12.0 漂到 13.7，导致搜索去抬黑位却越调越低分。
    所以第一次算出来后落盘，后续一律复用。
    """
    if os.path.exists(BIAS_PATH):
        return json.load(open(BIAS_PATH, encoding="utf-8"))
    return None


def save_bias(bias, note):
    json.dump({**{k: round(v, 3) for k, v in bias.items()}, "_note": note},
              open(BIAS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def ref_target():
    x, _ = frames(REF, 320, 180, 10)
    return tone_metrics(x)


def tone_rubric():
    rub = json.load(open(RUB, encoding="utf-8"))
    dim = next(d for d in rub["dimensions"] if d["key"] == "tone")
    return dim["items"]


def build_samples(cache):
    """(小图, 镜头 id) —— 只解码一次，之后每次搜索复用。"""
    cfg = json.load(open(os.path.join(ROOT, "shots", "shots.json"), encoding="utf-8"))["shots"]
    out = []
    for m in cfg:
        if m["art"] == "TITLE":
            continue
        p = os.path.join(ROOT, "assets", "shots", m["art"] + ".jpg")
        if not os.path.exists(p):
            continue
        sh = Shot(m, Image.open(p), cache)
        for f in FRACS:
            i = min(sh.n - 1, int(sh.n * f))
            out.append((sh.frame(i), m, i))
    return out


def evaluate(g, samples, cache, target, items, rng):
    acc = []
    for img, m, i in samples:
        r = post(img, cache, rng, i, m, g=g)
        acc.append(np.asarray(np2img(r).resize((320, 180), Image.LANCZOS), np.float32))
    x = np.stack(acc)
    M = tone_metrics(x)
    R = d_target = target
    scores, detail = [], {}
    for it in items:
        k = it["metric"]
        if it["kind"] == "similarity":
            s = sim_score(M[k], d_target[k], it["tol"])
        elif it["kind"] == "band":
            s = band_score(M[k], it["lo"], it["hi"], it.get("hard_lo"), it.get("hard_hi"))
        else:
            continue
        scores.append(s)
        detail[k] = (M[k], d_target[k], s)
    return float(np.mean(scores)), M, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="", help="逗号分隔的参数名，如 knee,gamma,sat")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VAL",
                    help="在搜索前覆盖基线参数，可重复：--set knee=0.72 --set gamma=0.86")
    ap.add_argument("--tag", default="", help="写进 jsonl 的标签，便于区分多轮搜索")
    a = ap.parse_args()

    cache = Cache(W, H)
    rng = np.random.default_rng(7)
    target = ref_target()
    items = tone_rubric()
    samples = build_samples(cache)
    print(f"抽样 {len(samples)} 帧 / {len(samples)//len(FRACS)} 镜；"
          f"参考 p95={target['luma_p95']:.1f} p5={target['luma_p5']:.1f} "
          f"luma={target['luma_mean']:.1f}")

    base = dict(GRADE)
    for kv in a.set:
        k, v = kv.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "cool_r":
            r = float(v)
            base["cool"] = (r, r + 0.14, 0.66)
        else:
            base[k] = float(v)
        print(f"基线覆盖 {k}={v}")

    s0, m0, _ = evaluate(base, samples, cache, target, items, rng)

    # 抽样偏差校正：只抽 2 帧/镜、且不含片名卡与淡入淡出，亮度必然偏高。
    # 用"同一组参数下 抽样值 − 成片实测值"作为偏差，把参考目标搬到抽样空间，
    # 这样再优化的是"回到参考片"，而不是"回到一个偏高的工作点"。
    bias = load_bias()
    film = film_metrics()
    if bias is None and film:
        bias = {k: m0[k] - film[k] for k in BIAS_KEYS if film.get(k) is not None}
        save_bias(bias, "由原始 GRADE 抽样 vs 当前成片实测得出；一经生成不再改变")
        print("抽样偏差已固化到 out/tone_bias.json")
    if bias:
        target = {**target, **{k: target[k] + bias[k] for k in BIAS_KEYS if k in bias}}
        print("抽样偏差校正：" + " ".join(f"{k}{bias[k]:+.1f}" for k in BIAS_KEYS if k in bias))
        s0, m0, _ = evaluate(base, samples, cache, target, items, rng)

    print(f"当前 GRADE：影调维度 {s0:.1f} 分  "
          f"luma={m0['luma_mean']:.1f} p5={m0['luma_p5']:.1f} p95={m0['luma_p95']:.1f} "
          f"sat={m0['sat']:.1f} teal={m0['teal']:.1f} gold={m0['gold']:.1f}")
    if not a.grid:
        return

    keys = [k.strip() for k in a.grid.split(",") if k.strip()]
    for k in keys:
        if k not in SPACE:
            raise SystemExit(f"未知参数 {k}，可选：{', '.join(SPACE)}")
    combos = list(itertools.product(*[SPACE[k] for k in keys]))
    print(f"网格 {len(combos)} 组：{keys}")

    results = []
    for n, vals in enumerate(combos, 1):
        g = dict(base)
        for k, v in zip(keys, vals):
            if k == "cool_r":
                g["cool"] = (v, v + 0.14, 0.66)
            else:
                g[k] = v
        s, m, _ = evaluate(g, samples, cache, target, items, rng)
        results.append((s, m, {k: v for k, v in zip(keys, vals)},
                        {"knee": g.get("knee"), "gamma": g.get("gamma"), "sat": g.get("sat"),
                         "cool": g.get("cool"), "black_lift": g.get("black_lift"),
                         "warm_hl": g.get("warm_hl")}))
        if n % 5 == 0 or n == len(combos):
            best = max(r[0] for r in results)
            print(f"  {n}/{len(combos)}  最好 {best:.1f}", flush=True)
            # 每 5 组落盘一次：长网格容易超时，结果不能只留在内存里
            with open(os.path.join(ROOT, "out", "tune_tone.jsonl"), "a", encoding="utf-8") as f:
                for s_, m_, v_, g_ in results[-5:]:
                    f.write(json.dumps(dict(score=round(s_, 2), params=v_, grade=g_, tag=a.tag,
                                            metrics={k: round(float(m_[k]), 3)
                                                     for k in ("luma_mean", "luma_p5",
                                                               "luma_p95", "sat", "teal",
                                                               "gold", "hi_clip", "lo_clip")}),
                                       ensure_ascii=False) + "\n")

    results.sort(key=lambda z: -z[0])
    print("\n前 5 名：")
    for s, m, v, gg in results[:5]:
        print(f"  {s:5.1f}  {v}  → luma={m['luma_mean']:.1f} p5={m['luma_p5']:.1f} "
              f"p95={m['luma_p95']:.1f} sat={m['sat']:.1f} teal={m['teal']:.1f} "
              f"gold={m['gold']:.1f} hi_clip={m['hi_clip']*100:.2f}%")

    best = results[0]
    print("\n最优组完整参数：")
    print(json.dumps(best[3], indent=1))

    if a.apply:
        p = os.path.join(ROOT, "render", "render_video.py")
        s = open(p, encoding="utf-8").read()
        i = s.index("GRADE = dict(")
        j = s.index(")\n", i) + 1
        g = dict(GRADE)
        g.update(best[3])
        body = ", ".join(f"{k}={v!r}" for k, v in g.items())
        s = s[:i] + f"GRADE = dict({body})" + s[j:]
        open(p, "w", encoding="utf-8").write(s)
        print("已写入 render/render_video.py 的 GRADE")


if __name__ == "__main__":
    main()
