@echo off
chcp 65001 >nul
cd /d %~dp0
title 企业知识问答 Agent - 生成全部验证材料
python -m src.kb_agent.cli demo
echo.
echo 已生成到 examples\ 目录,可打开各 case 目录中的 trace.md 查看。
pause
