@echo off
chcp 65001 >nul
cd /d %~dp0
title 企业知识问答 Agent - 多轮对话测试
echo 正在启动多轮对话(输入 exit 或 退出 结束)...
echo.
python -m src.kb_agent.cli chat
pause
