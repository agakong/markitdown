#!/bin/bash
# MarkItDown API 使用示例脚本

API_URL="http://localhost:8000"

echo "=== MarkItDown API 使用示例 ==="
echo ""

# 1. 检查服务健康状态
echo "1. 检查服务健康状态..."
curl -s "$API_URL/health" | jq .
echo ""

# 2. 查看队列状态
echo "2. 查看队列状态..."
curl -s "$API_URL/queue/status" | jq .
echo ""

# 3. 提交转换任务（请修改 filename 为实际存在的文件）
echo "3. 提交转换任务..."
RESPONSE=$(curl -s -X POST "$API_URL/convert" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "example.pdf",
    "callback_url": "http://your-callback-server.com/callback"
  }')

TASK_ID=$(echo $RESPONSE | jq -r '.task_id')
echo "响应: $RESPONSE"
echo "任务 ID: $TASK_ID"
echo ""

# 4. 查询任务状态
echo "4. 查询任务状态..."
sleep 2  # 等待一下再查询
curl -s "$API_URL/task/$TASK_ID" | jq .
echo ""

# 5. 列出所有任务
echo "5. 列出所有任务..."
curl -s "$API_URL/tasks" | jq .
echo ""

echo "=== 示例完成 ==="
