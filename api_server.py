#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarkItDown API Server
提供文件转换 API 接口，支持队列处理和回调机制
支持从阿里云 OSS 读取文件进行转换
"""
import os
import logging
import queue
import threading
import time
import uuid
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn
import oss2

from markitdown import MarkItDown

# 尝试导入 env.py 配置（如果不存在则使用环境变量）
try:
    from env import (
        OSS_ACCESS_KEY_ID,
        OSS_ACCESS_KEY_SECRET,
        OSS_ENDPOINT,
        OSS_BUCKET_NAME,
        CALLBACK_URL,
        MAX_RETRIES,
        CALLBACK_TIMEOUT,
        TEMP_DIR
    )
except ImportError:
    # 如果 env.py 不存在，使用环境变量
    OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
    OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-chengdu.aliyuncs.com")
    OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "markitdown")
    CALLBACK_URL = os.getenv("CALLBACK_URL", "")
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    CALLBACK_TIMEOUT = int(os.getenv("CALLBACK_TIMEOUT", "30"))
    TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/markitdown")

# 配置日志（支持中文）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # 确保使用 StreamHandler 以便正确处理 UTF-8
    ]
)
# 设置日志处理器的编码为 UTF-8
for handler in logging.root.handlers:
    if hasattr(handler, 'setStream'):
        # 确保日志输出使用 UTF-8 编码
        pass
logger = logging.getLogger(__name__)

# 全局变量
app = FastAPI(title="MarkItDown API Server", version="1.0.0")

# 转换队列
conversion_queue = queue.Queue()
queue_worker_thread = None
queue_lock = threading.Lock()

# 任务状态存储（简单实现，生产环境建议使用 Redis 等）
task_status: Dict[str, Dict[str, Any]] = {}

# 辅助函数：获取环境变量，如果为空则使用默认值
def get_env_or_default(key: str, default: str) -> str:
    """获取环境变量，如果未设置或为空字符串则返回默认值"""
    value = os.getenv(key, default)
    return value if value else default

# 配置
CONFIG = {
    # OSS 配置（从 env.py 或环境变量读取）
    "oss_access_key_id": OSS_ACCESS_KEY_ID,
    "oss_access_key_secret": OSS_ACCESS_KEY_SECRET,
    "oss_endpoint": OSS_ENDPOINT,
    "oss_bucket_name": OSS_BUCKET_NAME,
    # 回调配置
    "callback_url": CALLBACK_URL,
    "max_retries": MAX_RETRIES,
    "callback_timeout": CALLBACK_TIMEOUT,
    # 临时文件目录
    "temp_dir": TEMP_DIR,
}

# OSS 客户端（延迟初始化）
oss_auth = None
oss_bucket = None


def init_oss_client():
    """初始化 OSS 客户端"""
    global oss_auth, oss_bucket
    
    access_key_id = CONFIG["oss_access_key_id"].strip() if CONFIG["oss_access_key_id"] else ""
    access_key_secret = CONFIG["oss_access_key_secret"].strip() if CONFIG["oss_access_key_secret"] else ""
    endpoint = CONFIG["oss_endpoint"].strip() if CONFIG["oss_endpoint"] else ""
    bucket_name = CONFIG["oss_bucket_name"].strip() if CONFIG["oss_bucket_name"] else ""
    
    if not access_key_id or not access_key_secret:
        logger.warning("OSS 配置不完整，将无法从 OSS 读取文件")
        logger.warning(f"  AccessKey ID: {'已配置' if access_key_id else '未配置'}")
        logger.warning(f"  AccessKey Secret: {'已配置' if access_key_secret else '未配置'}")
        return None
    
    if not endpoint or not bucket_name:
        logger.warning("OSS Endpoint 或 Bucket 名称未配置")
        logger.warning(f"  Endpoint: {endpoint if endpoint else '未配置'}")
        logger.warning(f"  Bucket: {bucket_name if bucket_name else '未配置'}")
        return None
    
    # 更新 CONFIG 为处理后的值
    CONFIG["oss_access_key_id"] = access_key_id
    CONFIG["oss_access_key_secret"] = access_key_secret
    CONFIG["oss_endpoint"] = endpoint
    CONFIG["oss_bucket_name"] = bucket_name
    
    try:
        oss_auth = oss2.Auth(CONFIG["oss_access_key_id"], CONFIG["oss_access_key_secret"])
        oss_bucket = oss2.Bucket(oss_auth, CONFIG["oss_endpoint"], CONFIG["oss_bucket_name"])
        logger.info(f"OSS 客户端初始化成功: {CONFIG['oss_endpoint']}/{CONFIG['oss_bucket_name']}")
        return oss_bucket
    except Exception as e:
        logger.error(f"OSS 客户端初始化失败: {str(e)}")
        return None


@dataclass
class ConversionTask:
    """转换任务"""
    task_id: str
    oss_path: str  # OSS 文件路径
    callback_url: Optional[str] = None
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class ConversionRequest(BaseModel):
    """转换请求模型"""
    oss_path: str = Field(..., description="OSS 文件路径（相对于 Bucket 根目录，例如：files/document.pdf）")
    callback_url: Optional[str] = Field(None, description="回调 URL（可选，如果配置了全局回调 URL 则使用全局的）")


class ConversionResponse(BaseModel):
    """转换响应模型"""
    task_id: str = Field(..., description="任务 ID")
    status: str = Field(..., description="任务状态：queued, processing, completed, failed")
    message: str = Field(..., description="状态消息")


class TaskStatusResponse(BaseModel):
    """任务状态响应模型"""
    task_id: str
    status: str
    filename: str
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


def send_callback(callback_url: str, data: Dict[str, Any], task_id: str):
    """发送回调请求"""
    try:
        logger.info(f"任务 {task_id}: 发送回调到 {callback_url}")
        response = requests.post(
            callback_url,
            json=data,
            timeout=CONFIG["callback_timeout"],
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        logger.info(f"任务 {task_id}: 回调发送成功")
    except Exception as e:
        logger.error(f"任务 {task_id}: 回调发送失败: {str(e)}")


def process_conversion_task(task: ConversionTask, markitdown: MarkItDown):
    """处理单个转换任务"""
    task_id = task.task_id
    oss_path = task.oss_path
    callback_url = task.callback_url or CONFIG.get("callback_url")
    local_file_path = None
    
    # 更新任务状态为处理中
    with queue_lock:
        task_status[task_id] = {
            "task_id": task_id,
            "status": "processing",
            "filename": oss_path,  # 使用 oss_path 作为文件名显示
            "created_at": task.created_at,
            "completed_at": None,
            "error": None
        }
    
    logger.info(f"任务 {task_id}: 开始转换文件 {oss_path}")
    
    try:
        # 检查 OSS 客户端是否初始化
        if oss_bucket is None:
            error_msg = "OSS 客户端未初始化，请检查配置"
            logger.error(f"任务 {task_id}: {error_msg}")
            
            with queue_lock:
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = error_msg
                task_status[task_id]["completed_at"] = datetime.now().isoformat()
            
            if callback_url:
                send_callback(callback_url, {
                    "task_id": task_id,
                    "status": "failed",
                    "oss_path": oss_path,
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                }, task_id)
            return
        
        # 从 OSS 下载文件到临时目录
        logger.info(f"任务 {task_id}: 从 OSS 下载文件 {oss_path}")
        
        # 确保临时目录存在
        temp_dir = Path(CONFIG["temp_dir"])
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建临时文件
        file_extension = Path(oss_path).suffix or ".tmp"
        local_file_path = temp_dir / f"{task_id}{file_extension}"
        
        try:
            # 从 OSS 下载文件
            oss_bucket.get_object_to_file(oss_path, str(local_file_path))
            logger.info(f"任务 {task_id}: 文件下载成功，保存到 {local_file_path}")
        except oss2.exceptions.NoSuchKey:
            error_msg = f"OSS 文件不存在: {oss_path}"
            logger.error(f"任务 {task_id}: {error_msg}")
            
            with queue_lock:
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = error_msg
                task_status[task_id]["completed_at"] = datetime.now().isoformat()
            
            if callback_url:
                send_callback(callback_url, {
                    "task_id": task_id,
                    "status": "failed",
                    "oss_path": oss_path,
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                }, task_id)
            return
        except Exception as e:
            error_msg = f"从 OSS 下载文件失败: {str(e)}"
            logger.error(f"任务 {task_id}: {error_msg}", exc_info=True)
            
            with queue_lock:
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = error_msg
                task_status[task_id]["completed_at"] = datetime.now().isoformat()
            
            if callback_url:
                send_callback(callback_url, {
                    "task_id": task_id,
                    "status": "failed",
                    "oss_path": oss_path,
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                }, task_id)
            return
        
        # 执行转换
        logger.info(f"任务 {task_id}: 正在转换文件 {local_file_path}")
        result = markitdown.convert(str(local_file_path))
        markdown_content = result.markdown
        
        logger.info(f"任务 {task_id}: 转换成功，内容长度: {len(markdown_content)} 字符")
        
        # 更新任务状态为完成
        with queue_lock:
            task_status[task_id]["status"] = "completed"
            task_status[task_id]["completed_at"] = datetime.now().isoformat()
            task_status[task_id]["markdown_length"] = len(markdown_content)
        
        # 发送成功回调
        if callback_url:
            send_callback(callback_url, {
                "task_id": task_id,
                "status": "completed",
                "oss_path": oss_path,
                "markdown": markdown_content,
                "timestamp": datetime.now().isoformat()
            }, task_id)
        else:
            logger.warning(f"任务 {task_id}: 未配置回调 URL，跳过回调")
    
    except Exception as e:
        error_msg = f"转换失败: {str(e)}"
        logger.error(f"任务 {task_id}: {error_msg}", exc_info=True)
        
        # 更新任务状态为失败
        with queue_lock:
            task_status[task_id]["status"] = "failed"
            task_status[task_id]["error"] = error_msg
            task_status[task_id]["completed_at"] = datetime.now().isoformat()
        
        # 发送错误回调
        if callback_url:
            send_callback(callback_url, {
                "task_id": task_id,
                "status": "failed",
                "oss_path": oss_path,
                "error": error_msg,
                "timestamp": datetime.now().isoformat()
            }, task_id)
    
    finally:
        # 清理临时文件
        if local_file_path and local_file_path.exists():
            try:
                local_file_path.unlink()
                logger.info(f"任务 {task_id}: 临时文件已删除 {local_file_path}")
            except Exception as e:
                logger.warning(f"任务 {task_id}: 删除临时文件失败 {local_file_path}: {str(e)}")


def queue_worker():
    """队列工作线程，逐个处理转换任务"""
    logger.info("队列工作线程启动")
    
    # 初始化 MarkItDown 实例
    markitdown = MarkItDown(enable_plugins=False)
    
    while True:
        try:
            # 从队列获取任务（阻塞等待）
            task = conversion_queue.get(timeout=1)
            
            if task is None:  # 用于优雅关闭
                logger.info("收到关闭信号，队列工作线程退出")
                break
            
            # 处理任务
            process_conversion_task(task, markitdown)
            
            # 标记任务完成
            conversion_queue.task_done()
            
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"队列工作线程错误: {str(e)}", exc_info=True)
            time.sleep(1)  # 发生错误时稍作等待


def start_queue_worker():
    """启动队列工作线程"""
    global queue_worker_thread
    
    if queue_worker_thread is None or not queue_worker_thread.is_alive():
        queue_worker_thread = threading.Thread(target=queue_worker, daemon=True)
        queue_worker_thread.start()
        logger.info("队列工作线程已启动")


@app.on_event("startup")
def startup_event():
    """应用启动时执行"""
    logger.info("MarkItDown API Server 启动")
    logger.info(f"临时目录: {CONFIG['temp_dir']}")
    logger.info(f"OSS Bucket: {CONFIG.get('oss_bucket_name', '未配置')}")
    logger.info(f"OSS Endpoint: {CONFIG.get('oss_endpoint', '未配置')}")
    logger.info(f"回调 URL: {CONFIG.get('callback_url', '未配置')}")
    
    # 确保临时目录存在
    temp_dir = Path(CONFIG["temp_dir"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # 初始化 OSS 客户端
    init_oss_client()
    
    # 启动队列工作线程
    start_queue_worker()


@app.get("/")
def root():
    """根路径"""
    return {
        "service": "MarkItDown API Server",
        "version": "1.0.0",
        "status": "running",
        "queue_size": conversion_queue.qsize()
    }


@app.get("/health")
def health():
    """健康检查"""
    return {
        "status": "healthy",
        "queue_size": conversion_queue.qsize(),
        "worker_alive": queue_worker_thread.is_alive() if queue_worker_thread else False
    }


@app.post("/convert", response_model=ConversionResponse)
def convert_file(request: ConversionRequest):
    """提交转换任务"""
    # 检查 OSS 客户端是否初始化
    if oss_bucket is None:
        raise HTTPException(status_code=500, detail="OSS 客户端未初始化，请检查配置")
    
    # 验证 OSS 文件是否存在（可选，提前验证）
    oss_path = request.oss_path.strip()
    if not oss_path:
        raise HTTPException(status_code=400, detail="OSS 文件路径不能为空")
    
    try:
        # 检查文件是否存在（快速检查，不下载文件）
        if not oss_bucket.object_exists(oss_path):
            raise HTTPException(status_code=404, detail=f"OSS 文件不存在: {oss_path}")
    except Exception as e:
        logger.warning(f"检查 OSS 文件存在性时出错，将继续处理: {str(e)}")
        # 继续处理，实际下载时会再次检查
    
    # 生成任务 ID
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    
    # 创建任务
    callback_url = request.callback_url or CONFIG.get("callback_url")
    task = ConversionTask(
        task_id=task_id,
        oss_path=oss_path,
        callback_url=callback_url
    )
    
    # 添加到队列
    conversion_queue.put(task)
    
    # 记录任务状态
    with queue_lock:
        task_status[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "filename": oss_path,  # 使用 oss_path 作为显示名称
            "created_at": task.created_at,
            "completed_at": None,
            "error": None
        }
    
    logger.info(f"任务 {task_id}: 已加入队列，OSS 路径: {oss_path}")
    
    return ConversionResponse(
        task_id=task_id,
        status="queued",
        message="任务已加入队列"
    )


@app.get("/task/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str):
    """查询任务状态"""
    with queue_lock:
        if task_id not in task_status:
            # 任务不存在（可能是容器重启导致状态丢失），返回失败状态
            return TaskStatusResponse(
                task_id=task_id,
                status="failed",
                filename="",
                created_at="",
                completed_at=datetime.now().isoformat(),
                error="未找到对应的任务，可能是服务重启导致任务状态丢失"
            )
        
        status_info = task_status[task_id].copy()
        # 移除 markdown_length 等不需要返回的字段
        status_info.pop("markdown_length", None)
    
    return TaskStatusResponse(**status_info)


@app.get("/tasks")
def list_tasks():
    """列出所有任务状态"""
    with queue_lock:
        tasks = list(task_status.values())
    
    return {
        "total": len(tasks),
        "tasks": tasks
    }


@app.get("/queue/status")
def queue_status():
    """查询队列状态"""
    return {
        "queue_size": conversion_queue.qsize(),
        "worker_alive": queue_worker_thread.is_alive() if queue_worker_thread else False,
        "total_tasks": len(task_status)
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
