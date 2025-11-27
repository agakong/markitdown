# 启动服务

## 直接启动

```bash
docker compose up -d
```

## 启动并查看日志（前台运行，用于调试）

```bash
docker compose up
```

## 启动后验证

### 1. 检查服务状态

```bash
docker compose ps
```

### 2. 检查健康状态

```bash
curl http://localhost:8000/health
```

### 3. 查看服务日志

```bash
docker compose logs -f markitdown-api
```

## 停止服务

```bash
docker compose down
```

## 重新构建并启动（修改代码后）

```bash
docker compose up -d --build
```

## 注意事项

1. **首次启动**：首次构建镜像需要较长时间（下载依赖包），请耐心等待
2. **端口占用**：确保 8000 端口未被占用
3. **文件目录**：将待转换文件放入 `./data/input/` 目录
4. **回调 URL**：如需配置全局回调，取消 `docker-compose.yml` 中 `CALLBACK_URL` 的注释

## 常见问题

### 端口已被占用

修改 `docker-compose.yml` 中的端口映射：
```yaml
ports:
  - "8001:8000"  # 将主机端口改为 8001
```

### 构建失败

检查网络连接，确保可以访问 Docker Hub 和 PyPI。

### 服务启动失败

查看日志：
```bash
docker compose logs markitdown-api
```
