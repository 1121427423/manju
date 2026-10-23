#!/usr/bin/env python3
"""从 shots/shots.json 生成 SRT 字幕（成片的旁白/台词轨）。

只取有 caption 的镜头，时间用该镜的 t0→t1；字幕文本与画面内竖排文案完全一致。
用法: python3 scripts/make_srt.py [--out out/青冥·伞_40s.srt] [--shift 0.0]
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ts(t, sep=","):
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=os.path.join(ROOT, "shots", "shots.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "青冥·伞_40s.srt"))
    ap.add_argument("--shift", type=float, default=0.0, help="整体时间偏移（秒）")
    a = ap.parse_args()

    shots = json.load(open(a.shots, encoding="utf-8"))["shots"]
    cues = [s for s in shots if s.get("caption")]
    L = []
    for i, s in enumerate(cues, 1):
        t0, t1 = s["t0"] + a.shift, s["t1"] + a.shift
        # 末 0.05s 留给下一镜，避免字幕跨到切点之后
        L.append(str(i))
        L.append(f"{ts(t0)} --> {ts(max(t0 + 0.4, t1 - 0.05))}")
        L.append(s["caption"])
        L.append("")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    print(f"{len(cues)} 条字幕 → {a.out}")
    for s in cues:
        print(f"  {ts(s['t0'])}  {s['caption']}")


if __name__ == "__main__":
    main()
