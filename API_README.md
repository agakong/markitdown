# MarkItDown API Server 使用说明

## 概述

MarkItDown API Server 提供了一个 HTTP API 接口，用于将各种文件格式转换为 Markdown。它支持：

- ✅ 队列化处理（逐个文件转换）
- ✅ 回调机制（转换成功或失败时通知）
- ✅ Docker 部署，支持目录挂载
- ✅ 持续运行的服务

## 快速开始

### 1. 构建 Docker 镜像

```bash
docker build -t markitdown-api:latest .
```

### 2. 运行容器

#### 方式一：使用 docker run

```bash
docker run -d \
  --name markitdown-api \
  -p 8000:8000 \
  -v /path/to/your/files:/data/input:ro \
  -e CALLBACK_URL=http://your-callback-server.com/callback \
  markitdown-api:latest
```

#### 方式二：使用 docker-compose

1. 修改 `docker-compose.yml` 中的挂载目录路径：
   ```yaml
   volumes:
     - /path/to/your/files:/data/input:ro
   ```

2. 可选：设置回调 URL：
   ```yaml
   environment:
     - CALLBACK_URL=http://your-callback-server.com/callback
   ```

3. 启动服务：
   ```bash
   docker-compose up -d
   ```

### 3. 验证服务

```bash
curl http://localhost:8000/health
```

## API 接口

### 1. 提交转换任务

**POST** `/convert`

请求体：
```json
{
  "filename": "example.pdf",
  "callback_url": "http://your-callback-server.com/callback"  // 可选
}
```

**注意：**
- 支持中文文件名，例如：`"filename": "测试文档.pdf"`
- 文件名使用 UTF-8 编码
- 确保文件实际存在于挂载目录中

响应：
```json
{
  "task_id": "task_1234567890_12345",
  "status": "queued",
  "message": "任务已加入队列"
}
```

**示例：**
```bash
curl -X POST http://localhost:8000/convert \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "example.pdf",
    "callback_url": "http://your-callback-server.com/callback"
  }'
```

### 2. 查询任务状态

**GET** `/task/{task_id}`

响应：
```json
{
  "task_id": "task_1234567890_12345",
  "status": "completed",
  "filename": "example.pdf",
  "created_at": "2024-01-01T12:00:00",
  "completed_at": "2024-01-01T12:00:05",
  "error": null
}
```

**状态值：**
- `queued`: 任务已加入队列
- `processing`: 正在处理
- `completed`: 转换完成
- `failed`: 转换失败

**示例：**
```bash
curl http://localhost:8000/task/task_1234567890_12345
```

### 3. 列出所有任务

**GET** `/tasks`

**示例：**
```bash
curl http://localhost:8000/tasks
```

### 4. 查询队列状态

**GET** `/queue/status`

**示例：**
```bash
curl http://localhost:8000/queue/status
```

### 5. 健康检查

**GET** `/health`

**示例：**
```bash
curl http://localhost:8000/health
```

## 回调机制

### 成功回调

当文件转换成功时，系统会向指定的回调 URL 发送 POST 请求：

```json
{
  "task_id": "task_1234567890_12345",
  "status": "completed",
  "filename": "example.pdf",
  "markdown": "# 转换后的 Markdown 内容...",
  "timestamp": "2024-01-01T12:00:05"
}
```

### 失败回调

当文件转换失败时，系统会向指定的回调 URL 发送 POST 请求：

```json
{
  "task_id": "task_1234567890_12345",
  "status": "failed",
  "filename": "example.pdf",
  "error": "转换失败: 文件格式不支持",
  "timestamp": "2024-01-01T12:00:05"
}
```

### 回调 URL 配置

回调 URL 可以通过以下两种方式配置：

1. **环境变量**（全局默认）：
   ```bash
   -e CALLBACK_URL=http://your-callback-server.com/callback
   ```

2. **API 请求**（单次请求）：
   在 `/convert` 接口的请求体中指定 `callback_url`

如果两种方式都配置了，API 请求中的 `callback_url` 优先级更高。

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `INPUT_DIR` | 输入目录（容器内路径） | `/data/input` |
| `PORT` | API 服务端口 | `8000` |
| `HOST` | API 服务监听地址 | `0.0.0.0` |
| `CALLBACK_URL` | 回调 URL（可选） | `""` |
| `MAX_RETRIES` | 最大重试次数 | `3` |
| `CALLBACK_TIMEOUT` | 回调超时时间（秒） | `30` |

## 目录挂载

容器启动时需要将宿主机的文件目录挂载到容器的 `/data/input` 目录。

**示例：**
```bash
-v /home/user/documents:/data/input:ro
```

**注意：**
- `:ro` 表示只读挂载，推荐使用只读模式
- 确保挂载的目录中包含了待转换的文件
- 文件路径应该是相对于挂载目录的路径

**使用示例：**
```bash
# 挂载目录结构
/home/user/documents/
  ├── example.pdf
  └── document.docx

# API 请求
{
  "filename": "example.pdf"  // 只需要文件名，不需要完整路径
}
```

## 工作流程

1. 将待转换的文件放入挂载目录
2. 通过 API 提交转换任务（传入文件名）
3. 任务加入队列，等待处理
4. 队列工作线程逐个处理任务
5. 转换完成后，向回调 URL 发送结果（如果配置了）
6. 可以通过任务 ID 查询转换状态

## 故障排除

### 1. 文件不存在错误

**问题：** 收到 "文件不存在" 错误

**解决：**
- 检查文件是否在挂载目录中
- 检查文件名是否正确（包括扩展名）
- 检查目录挂载是否正确

### 2. 回调未收到

**问题：** 转换成功但没有收到回调

**解决：**
- 检查回调 URL 是否配置正确
- 检查回调服务器是否可访问
- 查看容器日志：`docker logs markitdown-api`

### 3. 队列不工作

**问题：** 任务一直处于 queued 状态

**解决：**
- 检查容器日志：`docker logs markitdown-api`
- 重启容器：`docker restart markitdown-api`
- 检查健康状态：`curl http://localhost:8000/health`

## 日志

查看容器日志：
```bash
docker logs -f markitdown-api
```

## 限制

- 队列是内存队列，容器重启后任务状态会丢失
- 建议在生产环境使用 Redis 等外部存储来持久化任务状态
- 当前实现是单线程处理，适合中小规模使用

## 示例：完整的转换流程

```bash
# 1. 启动服务
docker-compose up -d

# 2. 提交转换任务
TASK_ID=$(curl -X POST http://localhost:8000/convert \
  -H "Content-Type: application/json" \
  -d '{"filename": "example.pdf"}' \
  | jq -r '.task_id')

# 3. 查询任务状态
curl http://localhost:8000/task/$TASK_ID

# 4. 查看队列状态
curl http://localhost:8000/queue/status
```

## 注意事项

1. 确保挂载的目录有读取权限
2. 回调 URL 需要能从容器内访问到
3. 大文件转换可能需要较长时间，注意回调超时设置
4. 生产环境建议配置反向代理和 HTTPS
