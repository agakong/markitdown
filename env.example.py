# -*- coding: utf-8 -*-
"""
环境配置文件模板
复制此文件为 env.py 并填入实际的配置信息
注意：env.py 已添加到 .gitignore，不会被提交到 Git 仓库
"""

# OSS 配置
OSS_ACCESS_KEY_ID = "your_access_key_id_here"
OSS_ACCESS_KEY_SECRET = "your_access_key_secret_here"
OSS_ENDPOINT = "oss-cn-chengdu.aliyuncs.com"
OSS_BUCKET_NAME = "markitdown"

# 回调配置
CALLBACK_URL = ""  # 回调 URL（可选，也可通过 API 传递）
MAX_RETRIES = 3  # 最大重试次数
CALLBACK_TIMEOUT = 30  # 回调超时时间（秒）

# 临时文件目录
TEMP_DIR = "/tmp/markitdown"

