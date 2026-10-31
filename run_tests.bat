@echo off
chcp 65001 >nul
cd /d %~dp0
title 企业知识问答 Agent - 运行全部测试
python -m pytest tests/ -q
echo.
pause
