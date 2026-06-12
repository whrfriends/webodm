FROM webodm/nodeodx:latest

# 安装中文字体（Noto Sans CJK）
RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

# 替换 ODM 报告生成器为中文版本
# 原始文件: /code/SuperBuild/install/bin/opensfm/opensfm/report.py
COPY report_zh.py /code/SuperBuild/install/bin/opensfm/opensfm/report.py

# 验证
RUN python3 -c "import py_compile; py_compile.compile('/code/SuperBuild/install/bin/opensfm/opensfm/report.py', doraise=True)" && \
    ls -la /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
