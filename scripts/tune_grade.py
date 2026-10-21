#!/usr/bin/env python3
"""影调参数搜索：在 8 个代表性镜头上试参数，按"与参考片的影调距离"挑最优。

用法: python3 scripts/tune_grade.py [--grid] [--apply]
目标: 亮度均值 / 暗部 p5 / 高光 p95 / 饱和度 / 青绿 / 金色 六项同时逼近参考片，
      并约束高光溢出 <=2%、死黑 <=12%。
"""
import os, sys, json, itertools, argparse
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from render.lib.core import Cache, W, H, np2img
from render.lib.shot import Shot
from render.render_video import post, GRADE
from reviewer import tone_metrics, frames  # 复用评审者的同口径度量

REP_SHOTS = [1, 3, 5, 7, 10, 13, 17, 21]   # 覆盖亮/暗/特写/战斗/巨物
REF = os.path.join(ROOT, "original-720p.mp4")

WEIGHTS = dict(luma_mean=1.0, luma_p5=1.2, luma_p95=0.6, sat=0.9, teal=0.9, gold=0.6)


def ref_target():
    x, _ = frames(REF, 320, 180, 10)
    return tone_metrics(x)


def sample(g, shots, cache):
    cfg = {s["id"]: s for s in json.load(open(os.path.join(ROOT, "shots", "shots.json")))["shots"]}
    rng = np.random.default_rng(11)
    acc = []
    for sid in shots:
        m = cfg[sid]
        p = os.path.join(ROOT, "assets", "shots", m["art"] + ".jpg")
        if not os.path.exists(p):
            continue
        sh = Shot(m, Image.open(p), cache)
        for frac in (0.25, 0.6):
            i = min(sh.n - 1, int(sh.n * frac))
            img = post(sh.frame(i), cache, rng, i, m, g=g)
            # 下采样到与评审同口径
            small = np.asarray(np2img(img).resize((320, 180), Image.LANCZOS), np.float32)
            acc.append(small)
    x = np.stack(acc)
    return tone_metrics(x)


def cost(m, t):
    c = 0.0
    for k, w in WEIGHTS.items():
        scale = 12.0 if k in ("luma_mean", "sat") else (7.0 if k == "luma_p5" else 22.0)
        c += w * abs(m[k] - t[k]) / scale
    # 硬约束
    if m["hi_clip"] > 0.02:
        c += (m["hi_clip"] - 0.02) * 60
    if m["lo_clip"] > 0.12:
        c += (m["lo_clip"] - 0.12) * 40
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    cache = Cache(W, H)
    t = ref_target()
    print(f"参考片目标: luma={t['luma_mean']:.1f} p5={t['luma_p5']:.1f} p95={t['luma_p95']:.1f} "
          f"sat={t['sat']:.1f} teal={t['teal']:.1f} gold={t['gold']:.1f}")

    base = dict(GRADE)
    if a.grid:
        cands = []
        for roll, tr, tb in itertools.product([0.35, 0.65], [1.0, 0.96], [1.0, 1.05]):
            g = dict(base)
            g.update(lift=0.013, gamma=0.93, sat=0.95, vig=0.82, cool=(0.46, 0.56, 0.64),
                     hi_roll=roll, tint=(tr, 1.0, tb))
            cands.append(g)
        results = []
        for idx, g in enumerate(cands):
            m = sample(g, REP_SHOTS, cache)
            c = cost(m, t)
            results.append((c, g, m))
            if idx % 3 == 0:
                print(f"  {idx+1}/{len(cands)}  best={min(r[0] for r in results):.3f}", flush=True)
        results.sort(key=lambda z: z[0])
        print("\n前 3 名:")
        for c, g, m in results[:3]:
            print(f"  cost={c:.3f} luma={m['luma_mean']:.1f} p5={m['luma_p5']:.1f} "
                  f"p95={m['luma_p95']:.1f} sat={m['sat']:.1f} teal={m['teal']:.1f} gold={m['gold']:.1f}"
                  f"  roll={g['hi_roll']} tint={g['tint']}")
        best = results[0][1]
    else:
        m = sample(base, REP_SHOTS, cache)
        print(f"当前参数: cost={cost(m, t):.3f} luma={m['luma_mean']:.1f} p5={m['luma_p5']:.1f} "
              f"p95={m['luma_p95']:.1f} sat={m['sat']:.1f} teal={m['teal']:.1f} gold={m['gold']:.1f} "
              f"hi_clip={m['hi_clip']*100:.2f}% lo_clip={m['lo_clip']*100:.2f}%")
        return

    if a.apply:
        p = os.path.join(ROOT, "render", "render_video.py")
        s = open(p, encoding="utf-8").read()
        i = s.index("GRADE = dict(")
        j = s.index(")", i) + 1
        body = ", ".join(f"{k}={v!r}" for k, v in best.items())
        s = s[:i] + f"GRADE = dict({body})" + s[j:]
        open(p, "w", encoding="utf-8").write(s)
        print("已写入 render/render_video.py 的 GRADE")
    else:
        print("最优参数（未写入，加 --apply 应用）:")
        print(json.dumps(best, indent=1))


if __name__ == "__main__":
    main()
