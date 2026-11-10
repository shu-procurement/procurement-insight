@echo off
echo =========================================
echo       正在启动 Procurement System
echo       (使用 Anaconda 环境)
echo =========================================

:: 你的 Anaconda 环境名称
set CONDA_ENV_NAME=procurement_env

:: 启动 FastAPI 智能体后端 (设置端口为 8001)
echo [1/2] 正在启动 FastAPI 智能体服务...
start "FastAPI Agent Server" cmd /k "conda activate %CONDA_ENV_NAME% && cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload"

:: 等待 2 秒，错开启动时间
timeout /t 2 /nobreak > nul

:: 启动 Django 前端系统 (默认端口 8000)
echo [2/2] 正在启动 Django 前端服务...
start "Django Frontend Server" cmd /k "conda activate %CONDA_ENV_NAME% && cd frontend && python manage.py runserver 8000"

echo.
echo =========================================
echo 服务启动指令已发送！
echo 弹出的两个独立黑窗口中会带有 (%CONDA_ENV_NAME%) 前缀，请保持它们运行。
echo.
echo 前端访问地址: http://127.0.0.1:8000
echo =========================================
pause