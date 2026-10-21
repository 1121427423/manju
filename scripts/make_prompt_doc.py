#!/usr/bin/env python3
"""由 prompts/shots_prompts.json 生成 docs/02-分镜提示词包.md（保证文档与代码同源）。"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "prompts", "shots_prompts.json")))
meta = d["_meta"]

L = []
L.append("# 02 · 分镜提示词包（可直接投喂）\n")
L.append("> 本文件由 `scripts/make_prompt_doc.py` 从 `prompts/shots_prompts.json` 生成，**不要手改**。\n")
L.append("> 用法：先跑「关键帧」提示词出图（带 `refs` 里的参考图）→ 再做图生视频（`motion` 段）。\n")

L.append("## 0. 公共块（每条提示词都要拼上）\n")
L.append("**风格块**\n```\n" + meta["style_block"] + "\n```\n")
L.append("**负面词**\n```\n" + meta["negative"] + "\n```\n")
L.append("**玄罗定妆块**\n```\n" + meta["char_xuanluo"] + "\n```\n")
L.append("**照雪定妆块**\n```\n" + meta["char_zhaoxue"] + "\n```\n")
L.append("**场景块**\n```\n" + meta["scene"] + "\n```\n")

L.append("## 1. 角色一致性操作规范\n")
L.append("1. 先只跑一张玄罗 / 一张照雪的定妆三视图（`assets/keyart/`），**挑最满意的那张定稿**，之后不再改。\n")
L.append("2. 每条镜头提示词都上传定稿图作为 image reference（权重 0.45–0.6）。\n")
L.append("3. 同一角色所有镜头使用**同一个 seed**，只改镜头/动作/光线描述。\n")
L.append("4. 出现脸崩时，先用局部重绘（inpaint）只修脸，不要重跑整张。\n")
L.append("5. 全片两个角色**不能同框超过 3 个镜头**（远全景），否则一致性风险最高。\n")

L.append("\n## 2. 逐镜提示词\n")
for s in d["shots"]:
    L.append(f"### 镜头 {s['id']:02d} · `{s['art']}` · {s['dur']}s · {s['lens']}\n")
    L.append(f"- 参考图：{', '.join('`' + r + '`' for r in s['refs'])}")
    if s["image"].startswith("("):
        L.append(f"- 关键帧：{s['image']}\n")
    else:
        L.append("\n**关键帧（文生图）**\n```\n" + s["image"] + "\n\n" + meta["style_block"] + "\n```\n")
    L.append("**运动（图生视频）**\n```\n" + s["motion"] + "\n```\n")

L.append("\n## 3. 图生视频参数建议\n")
L.append("| 参数 | 建议值 | 说明 |\n|---|---|---|\n"
         "| 时长 | 1.2–3.0 s/镜 | 与 `shots.json` 的 `dur` 一致；超出就分段生成再剪 |\n"
         "| 运动强度 | 0.4–0.6 | 打斗镜头 0.7；特写 0.25（避免脸部形变） |\n"
         "| 镜头运动 | 与 `motion` 段一致 | 推 / 拉 / 摇 / 跟，尽量单一运动，避免「边推边转」 |\n"
         "| 帧率 | 生成 24fps → 交付 30fps | 用光流补帧，避免卡顿 |\n"
         "| 分辨率 | 1080p 生成 → 4K 放大 | 放大后再做胶片颗粒与暗角 |\n"
         "| 首尾帧 | 关键帧作为首帧 | 需要定格的一击，把同一张图作为尾帧（freeze） |\n")

L.append("\n## 4. 与后期管线的接法\n")
L.append("""生成好的镜头片段直接替换 `assets/shots/` 下的对应素材即可：

1. 把生成的视频按镜头切成 `assets/video_in/A01_feet.mp4` …（可选）
2. 若走「AI 视频」路线：`render/render_video.py` 改用视频输入，只做调色 + 特效叠加 + 剪辑
3. 若走「静帧 + 2.5D」路线（本仓库默认，零成本可跑）：用 `assets/shots/*.jpg` 直接渲染
4. 两条路线的**剪辑点、调色、音轨完全共用**，所以前期拆解和声音设计的钱不会白花
""")
open(os.path.join(ROOT, "docs", "02-分镜提示词包.md"), "w").write("\n".join(L))
print("ok", len(L), "lines")
