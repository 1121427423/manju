#!/usr/bin/env bash
# 一键复现：依赖安装 → 参考片分析 → 素材预处理 → 渲染 → 质检 → 衍生图
# 用法:  bash scripts/reproduce.sh            # 全片（缺素材的镜头自动跳过）
#        bash scripts/reproduce.sh 1,2,3      # 只跑指定镜头（快速验证）
set -euo pipefail
cd "$(dirname "$0")/.."

ONLY="${1:-}"
OUT="${2:-out/青冥·伞_40s.mp4}"

echo "== 0/5 依赖 =="
python3 -c "import numpy, PIL, imageio_ffmpeg" 2>/dev/null || \
  pip install --break-system-packages -q numpy pillow imageio-ffmpeg fonttools

echo "== 1/5 参考片量化拆解 =="
python3 scripts/analyze_ref.py original-720p.mp4 | tail -20

echo "== 2/5 素材预处理（16:9 裁切 + 联络表） =="
python3 scripts/prep_assets.py

echo "== 3/5 渲染（2 核 CPU 约 5 分钟） =="
if [ -n "$ONLY" ]; then
  python3 -m render.render_video --only "$ONLY" --out "$OUT"
else
  python3 -m render.render_video --out "$OUT"
fi

echo "== 4/5 质检 =="
python3 scripts/make_qc_doc.py "$OUT" 40

echo "== 5/5 衍生图 =="
python3 scripts/make_derived.py "$OUT"

echo "完成：$OUT"
