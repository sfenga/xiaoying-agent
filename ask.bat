@echo off
chcp 65001 >nul
cd /d %~dp0
if "%~1"=="" (
  echo 用法: ask.bat "你的问题" [--inject read_once]
  echo 示例: ask.bat "报销申请的期限是多久?"
  pause
  exit /b
)
python -m src.kb_agent.cli ask %*
echo.
pause
