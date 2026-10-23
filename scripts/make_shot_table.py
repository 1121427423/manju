#!/usr/bin/env python3
"""用 shots/shots.json 重写 docs/01 第六节的分镜表，避免文档与排期脱节。

分镜表曾经停留在 24 行（白闪与余波还是两镜），而 shots.json 早已合并为 23 镜，
于是文档写的和成片放的不是同一张表。改为生成，改 shots.json 即改文档。

用法: python3 scripts/make_shot_table.py [--check]
       --check  只比对，不写文件；不一致时退出码 1（可进 CI）
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "01-制作圣经.md")
HEADS = ("## 六、分镜表",)


def build(shots):
    L = [f"## 六、分镜表（{len(shots)} 镜 / {shots[-1]['t1']:.1f} s）", "",
         "> 完整机器可读版本见 `shots/shots.json`（渲染脚本直接读取，是唯一的排期真相；"
         "本表由 `scripts/make_shot_table.py` 从它生成）。", "",
         "| # | 时间 | 时长 | 景别/机位 | 画面 | 镜头运动 | 音效 |",
         "|---|---|---|---|---|---|---|"]
    for z in shots:
        L.append("| {id} | {t0:.1f}–{t1:.1f} | {d:.1f} | {lens} | {desc} | {move} | {sound} |".format(
            id=z["id"], t0=z["t0"], t1=z["t1"], d=z["t1"] - z["t0"],
            lens=z.get("lens", ""), desc=z.get("desc", ""),
            move=z.get("move", ""), sound=z.get("sound", "")))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    shots = json.load(open(os.path.join(ROOT, "shots", "shots.json"), encoding="utf-8"))["shots"]
    doc = open(DOC, encoding="utf-8").read()
    i = next(doc.index(h) for h in HEADS if h in doc)
    j = doc.index("\n## ", i + 10) + 1
    new = doc[:i] + build(shots) + "\n" + doc[j:]
    if a.check:
        print("分镜表与 shots.json " + ("一致" if new == doc else "不一致"))
        raise SystemExit(0 if new == doc else 1)
    open(DOC, "w", encoding="utf-8").write(new)
    print(f"docs/01 分镜表已按 shots.json 重写：{len(shots)} 镜")


if __name__ == "__main__":
    main()
