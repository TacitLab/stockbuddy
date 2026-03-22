#!/bin/bash

# Stock Buddy 启动脚本

echo "🚀 Stock Buddy 交易系统"
echo "======================="

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3"
    exit 1
fi

# 安装依赖
echo "📦 检查依赖..."
pip install -q -r backend/requirements.txt

# 初始化数据库
echo "🗄️  初始化数据库..."
cd backend
python3 -c "from database import init_db; init_db()"

# 启动后端
echo "🔥 启动后端服务 (http://localhost:8000)"
echo "📱 前端地址: http://localhost:8000/app"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
