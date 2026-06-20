@echo off
echo ========================================
echo  简历网站 - 本地服务器启动
echo ========================================
echo.
echo 使用 Python 启动 HTTP 服务...
echo.
cd /d "%~dp0"
start "" http://127.0.0.1:8000
python -m http.server 8000
pause
