# 快速开始指南

## 1. 构建镜像

```bash
docker build -t markitdown-api:latest .
```

## 2. 准备文件目录

创建本地目录并放入待转换的文件：

```bash
mkdir -p ./data/input
# 将待转换的文件放入 ./data/input 目录
cp your-file.pdf ./data/input/
```

## 3. 启动服务

### 方式一：使用 docker-compose（推荐）

```bash
# 修改 docker-compose.yml 中的挂载目录路径
docker-compose up -d
```

### 方式二：使用 docker run

```bash
docker run -d \
  --name markitdown-api \
  -p 8000:8000 \
  -v $(pwd)/data/input:/data/input:ro \
  -e CALLBACK_URL=http://your-callback-server.com/callback \
  markitdown-api:latest
```

## 4. 使用 API

### 提交转换任务

```bash
curl -X POST http://localhost:8000/convert \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "your-file.pdf"
  }'
```

### 查询任务状态

```bash
curl http://localhost:8000/task/{task_id}
```

### 查看所有任务

```bash
curl http://localhost:8000/tasks
```

## 5. 查看日志

```bash
docker logs -f markitdown-api
```

## 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `INPUT_DIR` | 输入目录 | `/data/input` |
| `PORT` | API 端口 | `8000` |
| `CALLBACK_URL` | 回调 URL | `""` |

更多详细信息请参阅 [API_README.md](./API_README.md)
