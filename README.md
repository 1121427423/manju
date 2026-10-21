# 青冥 · 伞 — 40 秒漫剧打斗先导片（AI 复刻工程）

> 目标：以 `original-720p.mp4`（39 s 漫剧打斗参考片）为标准，**复刻一条 40 秒的打斗短片**，
> 并把"怎么做出来的"全部落成可复现的文档与代码。

![关键帧联络表](docs/keyart_sheet.jpg)

---

## 成片

| | |
|---|---|
| 成片 | `out/青冥·伞_40s.mp4`（40.0 s / 1280×720 / 30 fps / H.264 + AAC） |
| 海报 | `out/poster.jpg` |
| 联络表 | `out/contact_sheet.jpg`（全片 20 格） |
| 音轨 | `out/score.wav`（40.0 s 立体声，程序化配乐） |
| 风格验证片 | `out/01_styleproof.mp4`（前 7 镜，用于快速校验影调与节奏） |

## 文档导航

| 文档 | 内容 |
|---|---|
| [`docs/00-参考视频拆解.md`](docs/00-参考视频拆解.md) | 参考片的量化逆向：切点、ASL、亮度/色偏曲线、响度、19 镜逐镜读图 |
| [`docs/01-制作圣经.md`](docs/01-制作圣经.md) | 创作思路、角色设定、场景、画面规范、VFX 清单、22 镜分镜表、文案 |
| [`docs/02-分镜提示词包.md`](docs/02-分镜提示词包.md) | 逐镜可直接投喂的提示词（关键帧 + 图生视频运动）、角色一致性规范 |
| [`docs/03-技术方案与工具链.md`](docs/03-技术方案与工具链.md) | 用了哪些工具、管线、算法、成本核算、已知差距、复现步骤 |
| [`docs/04-质检报告.md`](docs/04-质检报告.md) | 成片与参考片的逐项数值对比 + 自检清单 |

## 快速复现

```bash
pip install --break-system-packages numpy pillow imageio-ffmpeg fonttools

python3 scripts/analyze_ref.py original-720p.mp4   # 1) 复现参考片拆解数据
python3 scripts/prep_assets.py                     # 2) 关键帧裁切 16:9 + 联络表
python3 -m render.render_video                     # 3) 出片（2 核 CPU ≈ 5 分钟）
```

单镜头调试：

```bash
python3 -m render.render_video --only 11,17 --out out/debug.mp4 --no-audio
```

## 目录结构

```
├── original-720p.mp4          参考片（只做技法分析，不复用其角色/道具设计）
├── shots/shots.json           机器可读分镜表 —— 渲染的唯一排期真相
├── prompts/shots_prompts.json 逐镜提示词
├── assets/
│   ├── keyart/                角色定妆三视图 ×2 + 场景概念图
│   ├── shots/                 22 张镜头关键帧（16:9）
│   └── fonts/                 片名字体子集（26 KB）
├── render/
│   ├── render_video.py        合成主程序（运镜/VFX/调色/字幕/片名/编码）
│   └── lib/{core,vfx,shot,audio}.py
├── scripts/                   分析 / 素材预处理 / 文档生成
├── docs/                      00–04 文档
└── out/                       成片与衍生图
```

## 设计要点（一句话版）

- **结构照抄，符号原创**：继承参考片的"长铺垫 → 0.5 秒爆切 → 巨物反转"节奏公式，角色/道具/片名全部原创。
- **单一强色彩**：青绿 `#1F6B5E`/`#5FE3C0` + 古金 `#C9A24B`，全片占比 ≈ 60 / 7 %。
- **打击感四件套**：光 + 粒子 + 镜头抖 + 声音，每一击必须齐。
- **AI 只做质感，代码负责节奏**：图像模型出"真实感"，引擎管"什么时候动、动多快、响多重"。

## 免责声明

参考片仅用于结构与技法层面的分析；本片角色（玄罗 / 照雪 / 无相）、道具（九幽罗盘伞 / 素霜）、
片名与文案均为原创设定。成片含 AI 生成画面，公开发布需按平台要求标注"AI 辅助制作"。
