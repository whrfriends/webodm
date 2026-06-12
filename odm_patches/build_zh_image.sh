#!/bin/bash
# 构建带中文报告支持的 nodeodx 镜像
# 用法: ./build_zh_image.sh
# 完成后在 docker-compose.nodeodm.yml 把 image: webodm/nodeodx 改为 webodm/nodeodx:zh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"
docker build -t webodm/nodeodx:zh .

echo ""
echo "镜像构建完成: webodm/nodeodx:zh"
echo ""
echo "修改 docker-compose.nodeodm.yml 中:"
echo "  image: webodm/nodeodx"
echo "改为:"
echo "  image: webodm/nodeodx:zh"
echo ""
echo "然后重启容器,新生成的所有 report.pdf 都是中文版。"
