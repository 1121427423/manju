#!/usr/bin/env bash
# 沙箱环境被重置后的恢复脚本（本工程已遇到 4 次，每次人工恢复约 20 分钟，故固化）。
#
# 做的事，按顺序：
#   1. 把当前工作树备份到 /tmp/manju_backup_<时间戳>（避免误删未提交的实验）
#   2. 从 origin 重新同步分支（默认只 fetch + 报告差异；加 --sync 才真正对齐）
#   3. 安装渲染/评审依赖
#   4. 自检：成片存在且能被 ffprobe 读出 1200 帧、素材/分镜/评审文件齐全
#   5. 打印磁盘占用与后续命令
#
# 用法:
#   bash scripts/restore.sh                 # 保守模式：只备份 + 装依赖 + 自检
#   bash scripts/restore.sh --sync          # 对齐远端（本地有未提交改动会先备份）
#   bash scripts/restore.sh --sync --ref <branch>   # 指定远端分支
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

SYNC=0
REF="arena/f4ee7e05-manju"
while [ $# -gt 0 ]; do
  case "$1" in
    --sync) SYNC=1; shift ;;
    --ref)  REF="${2:-$REF}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

TS="$(date +%Y%m%d-%H%M%S)"
BAK="/tmp/manju_backup_$TS"

echo "== 1/5 备份工作树 → $BAK =="
mkdir -p "$BAK"
# 只备份源码/素材/输出索引，跳过 .git（几百 MB）与可重算的中间物
for d in render scripts shots docs assets review prompts out README.md original-720p.mp4; do
  [ -e "$d" ] && cp -a "$d" "$BAK/" 2>/dev/null
done
echo "   备份大小: $(du -sh "$BAK" 2>/dev/null | cut -f1)"

echo "== 2/5 Git 同步（分支 $REF） =="
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "   ⚠️ 不是 git 仓库，跳过同步"; else
  git fetch origin "$REF" --quiet 2>/dev/null || echo "   ⚠️ fetch 失败（离线？），使用本地对象"
  LOCAL="$(git rev-parse --short HEAD 2>/dev/null || echo none)"
  REMOTE="$(git rev-parse --short "origin/$REF" 2>/dev/null || echo none)"
  echo "   local=$LOCAL  origin/$REF=$REMOTE"
  DIRTY="$(git status --porcelain | wc -l | tr -d ' ')"
  echo "   未提交改动: $DIRTY 个文件"
  if [ "$SYNC" = 1 ] && [ "$REMOTE" != none ]; then
    if [ "$DIRTY" != 0 ]; then
      echo "   先把当前改动存成 stash（可用 git stash pop 找回）"
      git stash push -u -m "restore.sh@$TS" >/dev/null || true
    fi
    git reset --hard "origin/$REF" >/dev/null && echo "   ✅ 已对齐 origin/$REF ($REMOTE)"
  elif [ "$LOCAL" != "$REMOTE" ]; then
    echo "   ℹ️ 与远端不一致；如确认要丢弃本地改动，重跑： bash scripts/restore.sh --sync"
  fi
fi

echo "== 3/5 依赖 =="
python3 - <<'PY' || pip install --break-system-packages -q numpy pillow imageio-ffmpeg fonttools
import numpy, PIL, imageio_ffmpeg, sys
print("   numpy", numpy.__version__, "/ Pillow", PIL.__version__, "/ imageio-ffmpeg ok")
PY

echo "== 4/5 自检 =="
FAIL=0
need=(
  "render/render_video.py" "shots/shots.json" "scripts/reviewer.py"
  "review/rubric.json" "docs/01-制作圣经.md" "docs/07-评审报告.md"
  "out/青冥·伞_40s.mp4" "out/score.wav" "out/青冥·伞_40s.srt"
)
for f in "${need[@]}"; do
  if [ -e "$f" ]; then printf '   ✅ %s (%s)\n' "$f" "$(du -h "$f" | cut -f1)"
  else printf '   ❌ 缺失 %s\n' "$f"; FAIL=1; fi
done
if [ -e "out/青冥·伞_40s.mp4" ]; then
  R="$(python3 - <<'PY'
import re, subprocess
import imageio_ffmpeg

ff = imageio_ffmpeg.get_ffmpeg_exe()
# imageio-ffmpeg 只带 ffmpeg、不带 ffprobe：用 showinfo 数帧（1200 帧约 3 秒）
p = subprocess.run([ff, "-hide_banner", "-i", "out/青冥·伞_40s.mp4",
                    "-vf", "showinfo", "-an", "-f", "null", "-"],
                   capture_output=True, text=True)
frames = len(re.findall(r"\bn:\s*\d+.*pts_time:", p.stderr))
size = re.search(r"Video:.*?, (\d{2,5}x\d{2,5})", p.stderr)
fps = re.search(r"(\d+(?:\.\d+)?) fps", p.stderr)
print("{} {} {}帧".format(size.group(1) if size else "?",
                        fps.group(1) + "fps" if fps else "?", frames))
PY
)"
  echo "   成片: $R"
  case "$R" in *1200帧*) ;; *) [ "$R" = "ffprobe 不可用，跳过帧数核对" ] || { echo "   ❌ 帧数不是 1200，可能是不完整版本"; FAIL=1; } ;; esac
fi

echo "== 5/5 磁盘 =="
du -sh .git out assets 2>/dev/null | sed 's/^/   /'

if [ "$FAIL" != 0 ]; then
  echo "❌ 自检未通过，见上面 ❌ 项"; exit 1
fi
echo "✅ 环境就绪。出片: python3 -m render.render_video · 评审: python3 scripts/reviewer.py"
