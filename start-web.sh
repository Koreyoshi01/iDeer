#!/bin/bash

# Daily Recommender Web UI 启动脚本

cd "$(dirname "$0")"

echo "╔════════════════════════════════════════════════════════╗"
echo "║          Daily Recommender Web Server                  ║"
echo "╠════════════════════════════════════════════════════════╣"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "║  创建虚拟环境...                                       ║"
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
echo "║  安装/检查依赖...                                      ║"
pip install -q -r requirements-web.txt

# 创建必要的目录
mkdir -p profiles history

# 启动服务器
echo "║                                                        ║"
echo "║  🚀 启动服务器...                                       ║"
echo "║                                                        ║"
echo "║  📱 Web UI:   http://localhost:8080                    ║"
echo "║  📚 API Docs: http://localhost:8080/docs               ║"
echo "║  ❤️  Health:  http://localhost:8080/health             ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

python web_server.py
