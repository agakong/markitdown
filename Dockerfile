FROM python:3.13-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive
ENV EXIFTOOL_PATH=/usr/bin/exiftool
ENV FFMPEG_PATH=/usr/bin/ffmpeg

# Runtime dependency
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    exiftool

ARG INSTALL_GIT=false
RUN if [ "$INSTALL_GIT" = "true" ]; then \
    apt-get install -y --no-install-recommends \
    git; \
    fi

# Cleanup
RUN rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip --no-cache-dir install \
    /app/packages/markitdown[all] \
    /app/packages/markitdown-sample-plugin

# 安装 API 服务器依赖
COPY requirements-api.txt /app/
RUN pip --no-cache-dir install -r requirements-api.txt

# 创建数据目录（用于挂载）
RUN mkdir -p /data/input && chmod 777 /data/input

# Default USERID and GROUPID (注释掉，使用 root 以便访问挂载的目录)
# ARG USERID=nobody
# ARG GROUPID=nogroup
# USER $USERID:$GROUPID

# 暴露 API 端口
EXPOSE 8000

# 设置环境变量默认值
ENV INPUT_DIR=/data/input
ENV PORT=8000
ENV HOST=0.0.0.0
ENV CALLBACK_URL=""
ENV MAX_RETRIES=3
ENV CALLBACK_TIMEOUT=30

# 启动 API 服务器（默认行为）
# 如果需要使用原始的 markitdown CLI，可以通过 docker run 覆盖命令
CMD ["python", "api_server.py"]
