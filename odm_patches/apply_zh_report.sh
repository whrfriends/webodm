#!/bin/bash
# 把中文版 ODM 报告重新注入到运行中的 node-odx 容器
# 用法: ./apply_zh_report.sh
#
# 适用场景: 容器重启后 / 重新部署后丢失了中文 PDF 修改
# 不需要重建镜像（如果想永久生效,使用 build_zh_image.sh 构建自定义镜像）

set -e

CONTAINER="${1:-node-odx-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">>> 1/3 注入中文 report.py 到 $CONTAINER"
docker cp "$SCRIPT_DIR/report_zh.py" "$CONTAINER:/code/SuperBuild/install/bin/opensfm/opensfm/report.py"

echo ">>> 2/3 安装中文字体 (apt-get install fonts-noto-cjk)"
docker exec "$CONTAINER" bash -c "apt-get install -y fonts-noto-cjk 2>&1 | tail -3"

echo ">>> 3/3 验证 Python 语法 + 字体可用"
docker exec "$CONTAINER" python3 -c "
import py_compile
py_compile.compile('/code/SuperBuild/install/bin/opensfm/opensfm/report.py', doraise=True)
import os
assert os.path.isfile('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'), '字体未安装'
print('OK: 中文报告补丁已应用')
"

echo ""
echo ">>> 提示: 重新跑一个任务,生成的 report.pdf 即为中文版"
echo ">>> 永久方案: docker build -t webodm/nodeodx:zh $SCRIPT_DIR"
