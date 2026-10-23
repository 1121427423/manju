# 3 秒图生视频 · agnes-video-2.5-flash（keyframe 双锚）

依据 `out/review/video3s_refs/README.md` 的参考帧与提示词产出。提示词逐字复用该 README，
未在别处另写一版（两版提示词迟早会漂，参考帧已经踩过一次这种坑）。

## 产出

| 文件 | 内容 |
|------|------|
| `video3s_agnes-video-2.5-flash_keyframe_raw.mp4` | 上游原片：1260×720 / 24fps / 4.48s（上游最小 4 秒） |
| `video3s_agnes-video-2.5-flash_keyframe_3s.mp4` | 按分镜裁到 3 秒（stream copy，不重编码） |
| `video3s_agnes-video-2.5-flash_keyframe_3s_720p.mp4` | 再统一到 1280×720（CRF 18 / 24fps / 3.083s / 74 帧） |
| `video3s_agnes-video-2.5-flash_keyframe_sheet.jpg` | 12 格联络表（每 0.4s 一格），快速核动作节拍 |
| `qc/f000 f150 f220 f300 f440.jpg` | 0.0 / 1.5 / 2.2 / 3.0 / 4.4s 关键帧 |
| `video3s_agnes-video-2.5-flash_keyframe.json` | 任务元数据：video_id、直链、请求体、探测结果 |

## 请求参数（实测生效的取值）

```
model        agnes-video-2.5-flash     # flash 只有 720P 档；$0/秒（限时免费）
mode         keyframe                  # 双锚：first_frame + last_frame
first_frame  .../video3s_refs/00_start.jpg
last_frame   .../video3s_refs/02_end.jpg
seconds      "4"                       # 字符串，上游最小 4、最大 12；出片后裁到 3s
size         720P
aspect_ratio 16:9
```

`video3s_refs` 的 3 张图已提交进公开仓库，视频接口只吃公网 URL（`_shared/docs` 坑位 §5.21：
生图接口没有上传端点）。所以参考帧用 raw 链接喂，脚本在上传前会比**字节长度 + sha256**，
防止 URL 指向另一张图（§5.26 的教训：同源要验内容，不能验文件名）。

## 走哪条链路（2026-10-24 实测，与旧记录不同）

| 路线 | 结果 |
|------|------|
| 网关 `127.0.0.1:8080` `/v1/videos`（`agnes/` 与 `cn-agens/` 两条路由） | **404** `endpoint is not enabled on this gateway: /v1/videos`（端点 allowlist 未开）—— 不是渲染返空体，任务根本没建起来 |
| 直连 `apihub.agnes-ai.com` + `AGNES_TOKEN_PLAN_KEY`（cpk-） | **通**：text 与 keyframe 两种模式都能排队 → in_progress → completed 并拿到直链 |

旧记录里"中国站是唯一能出视频的路径"已不成立：本次两镜任务全走国际站，
cpk- key 直连即可。中国站免费 sk- key（`/tmp/.agnes_test_key`）在本机已不存在。

## 质量核验（数值，不靠眼感）

| 指标 | 结果 | 判读 |
|------|------|------|
| 首帧 vs `00_start.jpg` NCC | **0.997** | 起始构图/姿势等同参考帧 |
| 末帧 vs `02_end.jpg` NCC | **0.883** | 尾段落入参考结束状态（未完全重合，见下"已知偏差"） |
| 首帧 vs `02_end` / 末帧 vs `00_start` | 0.673 / 0.647 | 对照组偏低 → 首尾不是同一姿势，动作确实跑完了 |
| 帧间均值 \|diff\|（11 步） | 均值 11.67 / 峰值 39.75（≈1.2s 处） | 峰值落在突进段，不是静帧推拉 |

逐帧看下来：起势 → 突进（1.2–1.5s 峰值）→ 剑尖触伞迸金青火花 → 撤步沉剑 → 停在尾帧姿势，
背景塔、圆形石台、石柱位置稳定，没有切镜、变焦或全屏波纹。

## 已知偏差 / 取舍

1. **`01_clash.jpg` 没有喂进去。** keyframe 模式下 `first_frame`/`last_frame` 与
   `images[]` 互斥，中间锚图塞不进同一次调用；而 `01_clash` 的女剑客是露腿长裙、伞面制式
   也与首尾帧不同，作为外观参考会拉漂服装。要试 `reference` 模式可跑：
   `python3 scripts/make_video3s.py --mode reference --with-clash`。
2. **末帧 NCC 0.883 而非 0.99。** 视频在 4.4s 结尾时男剑客已撤半步、剑尖沉向地面，
   姿态比 `02_end` 更"收"一点；裁到 3.0s 的版本更接近参考尾帧（`qc/f300.jpg`）。
   若要求严格停在尾帧，可只取前 3 秒（本目录的 `_3s` 版本即如此）。
3. **原生 1260×720 而非 1280×720。** 上游按参考帧的 1376×768 推算画幅；`_720p` 版本用
   一次 `scale=1280:720` 统一，肉眼无差（横向拉伸 0.8%）。
4. **无音轨。** 视频默认不带声音，配音/音效按 `04-voice` 那套另做。

## 复现

```bash
cd ~/BigModel/LLM/tools/manju
export AGNES_TOKEN_PLAN_KEY=$(grep AGNES_TOKEN_PLAN_KEY ~/.zshrc | sed "s/.*=//; s/['\"]//g")
python3 scripts/make_video3s.py --mode keyframe --dry-run   # 先看请求体
python3 scripts/make_video3s.py --mode keyframe             # 建任务→轮询→下载→裁 3s→联络表
```

脚本自带 429/503 指数退避（70s→300s）、`model_name` 轮询、mp4 魔数校验（`ftyp`）；
参考图本机校验要过代理（`REF_PROXY`，默认 `http://127.0.0.1:10987`），取不到只告警不阻断
（挡在本地的是代理，不挡上游取图）。

本次任务：`video_id=task_pcDfkew54FOddw6HM9VL6h9rdR3fDHny`，排队→完成 154s。

---

## v2：针对性改写的第二版（`prompt v2_action`）

v1 的三处偏差（开场停顿偏长、女方挡击反应弱、碰撞闪光偏强）用同一套提示词无法修，
所以这一版换了提示词，**不动参考帧**：仍 `00_start.jpg` 首帧 + `02_end.jpg` 尾帧。

提示词不再内嵌在脚本里，改放文件：

| | 位置 | sha256（前 16） |
|---|---|---|
| v1 | `scripts/make_video3s.py` 内嵌（逐字取自 `video3s_refs/README.md`） | — |
| v2 | `out/review/video3s_refs/prompts/v2_action.json` | `d838fa7f2abbda01` |

元数据 json 里新增 `prompt_version` / `prompt_file` / `prompt_sha256`，
所以"哪一版提示词出了哪条片"可追溯（改提示词就换文件，不破坏已出片的可复现性）。

v2 提示词要点：0–0.2s 对峙、**0.2–0.85s 突进**、0.85–1.25s 剑盾接触 + 女剑客肩躯受力回弹、
1.25–2.2s 撤步沉剑、2.2–3.0s 收住。因为接口强制 4 秒，末尾追加了一段时长约束：
**前 3 秒完成全部动作，第 3–4 秒保持结束姿势**，再裁前 3 秒。

### 产出

| 文件 | 内容 |
|------|------|
| `video3s_agnes-video-2.5-flash_keyframe_v2_action_raw.mp4` | 上游原片：1260×720 / 24fps / 4.48s |
| `..._v2_action_3s.mp4` | 裁到 3 秒（stream copy） |
| `..._v2_action_3s_720p.mp4` | 1280×720 / 24fps / 74 帧 / 3.083s（CRF 18） |
| `..._v2_action_sheet.jpg` | 12 格联络表（每 0.4s 一格，盖到 4.0s） |
| `..._v2_action.json` | 元数据：video_id、提示词版本/sha、三段 probe、qc 指针 |
| `compare_v1_v2.jpg` | v1（上排）与 v2（下排）同时间码并排，8 格，0–3.0s |
| `qc_v1_v2.json` | 两版的全部 QC 数值（`scripts/qc_video3s.py` 产出） |

本次任务：`video_id=task_kOPq7WzCsZPP9clV8enWu2dpzcrKU9WO`，排队→完成 183s。

### 三处偏差的对照（同一口径，`scripts/qc_video3s.py`）

| 指标 | v1 | v2 | 判读 |
|------|----|----|------|
| 明显运动起点 `motion_onset_s` | 1.17s | **0.67s** | 前 1 秒帧间差 v1 恒定在 0.3–1.1（雨量级），v2 在 0.54s 抬到 1.1、0.63s 到 3.3、0.92s 到 10.1 |
| 运动峰值时刻 | 1.50s | **1.08s** | 突进/接触整体提前约 0.4s |
| 单帧最大跳变 | 17.6 | 14.2 | v2 无 >15 的瞬移帧（v1 有 1 帧） |
| 女方侧（右半）运动能量 0.2–1.3s | 0.5 | **3.5** | 女剑客侧几乎不动 → 抬盾迎击，7 倍 |
| 男方侧（左半）运动能量 | 2.2 | 5.0 | 突进幅度同时变大（见下方残留问题） |
| 纯白闪光峰值占面 | 1.06% @1.58s | **0.18% @1.08s** | 5.9×；>0.2% 的帧 23 → **0** |
| 泛白光斑（白闪+金火花）峰值 | 4.79% | **1.98%** | 观感上的"光太强"降 2.4× |
| 泛白光斑在场期间平均占面 | 1.72% | **0.45%** | 3.8× |
| 金色像素峰值 | 0.07%（几乎没有） | 0.29% | v1 出的是青白闪，v2 才是提示词要的"金色火花" |
| 首帧 vs `00_start` NCC | 0.997 | 0.997 | 双锚未跑偏 |
| 末帧 vs `02_end` NCC | 0.863 | 0.869 | 同级；见下方"火花收不掉"的原因 |

### v2 的已知偏差 / 取舍

1. **火花收不到零，是被尾锚逼的。** 提示词写"2.2–3.0s 火花熄灭"，但 `02_end.jpg`
   本身在伞面边缘就带一簇金色火花（见 `video3s_refs/02_end.jpg`），keyframe 模式会插值到尾帧，
   所以两版到尾段都还亮着。v2 做的是把光斑**做小做金**（泛白光斑 4.79%→1.98%），
   而不是归零。要真归零得换尾帧图，或改 `reference` 模式（放弃强尾锚）。
2. **突进比 v1 猛。** 男剑客 0.9–1.5s 前倾很深、位移大，攻击性更强但也更容易显得"扑"。
   若嫌过猛，v3 可加一句"突进步幅不超过半步，重心始终在石台圆盘内"。
3. **0–0.5s 仍有约半秒的微动段**（0.2–0.7 量级，属雨/呼吸级）。比 v1 的 1.17s 短，但没到提示词
   写的 0.2s 起势；再压需要把首个时间窗改得更狠（例如"0–0.1s 即重心前移"）。
4. **原生 1260×720**，同 v1，`_720p` 版统一到 1280×720。
   注意：脚本首轮给 720p 转码加了 `-r 24`，把 74 帧揉成 77 帧/3.208s（时间戳重排），
   已去掉该参数重编，现为 74 帧/3.083s —— 与 `_3s` 版本逐帧对齐。
5. **无音轨**，同 v1。

### 复现

```bash
cd ~/BigModel/LLM/tools/manju
python3 scripts/make_video3s.py --prompt-file v2_action.json --dry-run   # 先看请求体
python3 scripts/make_video3s.py --prompt-file v2_action.json             # 出片
python3 scripts/qc_video3s.py \
  --a out/review/video3s/video3s_agnes-video-2.5-flash_keyframe_raw.mp4 \
  --b out/review/video3s/video3s_agnes-video-2.5-flash_keyframe_v2_action_raw.mp4 \
  --sheet out/review/video3s/compare_v1_v2.jpg --json out/review/video3s/qc_v1_v2.json
```

`--prompt-file` 只认文件名时会自动到 `out/review/video3s_refs/prompts/` 下找；
`--tag` 缺省取提示词的 `version`（所以 v1 保持原文件名、v2 带 `_v2_action` 后缀，互不覆盖）。
