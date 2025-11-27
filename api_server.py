#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarkItDown API Server
提供文件转换 API 接口，支持队列处理和回调机制
"""
import os
import logging
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from markitdown import MarkItDown

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

# 配置
CONFIG = {
    "input_dir": os.getenv("INPUT_DIR", "/data/input"),  # 挂载的输入目录
    "callback_url": os.getenv("CALLBACK_URL", ""),  # 回调 URL（可选，也可通过 API 传递）
    "max_retries": int(os.getenv("MAX_RETRIES", "3")),  # 最大重试次数
    "callback_timeout": int(os.getenv("CALLBACK_TIMEOUT", "30")),  # 回调超时时间（秒）
}


@dataclass
class ConversionTask:
    """转换任务"""
    task_id: str
    filename: str
    callback_url: Optional[str] = None
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class ConversionRequest(BaseModel):
    """转换请求模型"""
    filename: str = Field(..., description="待转换的文件名（相对于输入目录）")
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
    filename = task.filename
    callback_url = task.callback_url or CONFIG.get("callback_url")
    
    # 更新任务状态为处理中
    with queue_lock:
        task_status[task_id] = {
            "task_id": task_id,
            "status": "processing",
            "filename": filename,
            "created_at": task.created_at,
            "completed_at": None,
            "error": None
        }
    
    logger.info(f"任务 {task_id}: 开始转换文件 {filename}")
    
    try:
        # 构建文件完整路径
        input_dir = Path(CONFIG["input_dir"])
        file_path = input_dir / filename
        
        # 检查文件是否存在
        if not file_path.exists():
            error_msg = f"文件不存在: {filename}"
            logger.error(f"任务 {task_id}: {error_msg}")
            
            with queue_lock:
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = error_msg
                task_status[task_id]["completed_at"] = datetime.now().isoformat()
            
            # 发送错误回调
            if callback_url:
                send_callback(callback_url, {
                    "task_id": task_id,
                    "status": "failed",
                    "filename": filename,
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                }, task_id)
            
            return
        
        # 执行转换
        logger.info(f"任务 {task_id}: 正在转换文件 {file_path}")
        result = markitdown.convert(str(file_path))
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
                "filename": filename,
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
                "filename": filename,
                "error": error_msg,
                "timestamp": datetime.now().isoformat()
            }, task_id)


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
    logger.info(f"输入目录: {CONFIG['input_dir']}")
    logger.info(f"回调 URL: {CONFIG.get('callback_url', '未配置')}")
    
    # 确保输入目录存在
    input_dir = Path(CONFIG["input_dir"])
    input_dir.mkdir(parents=True, exist_ok=True)
    
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
    # 验证文件是否存在
    input_dir = Path(CONFIG["input_dir"])
    file_path = input_dir / request.filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {request.filename}")
    
    # 生成任务 ID
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    
    # 创建任务
    callback_url = request.callback_url or CONFIG.get("callback_url")
    task = ConversionTask(
        task_id=task_id,
        filename=request.filename,
        callback_url=callback_url
    )
    
    # 添加到队列
    conversion_queue.put(task)
    
    # 记录任务状态
    with queue_lock:
        task_status[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "filename": request.filename,
            "created_at": task.created_at,
            "completed_at": None,
            "error": None
        }
    
    logger.info(f"任务 {task_id}: 已加入队列，文件: {request.filename}")
    
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
