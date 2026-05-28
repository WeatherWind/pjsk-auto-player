@echo off
REM PJSK Auto Player — 一键启动脚本 (Windows)
chcp 65001 >nul

echo.
echo   ╔════════════════════════════════════════╗
echo   ║     PJSK Auto Player — 一键启动        ║
echo   ╚════════════════════════════════════════╝
echo.

REM 检查 Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Python 未安装。请先安装 Python 3.8+
    echo    https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✅ Python: 
python --version

REM 安装依赖
python -c "import cv2, numpy, yaml" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo 📦 安装依赖...
    python -m pip install --upgrade pip -q
    python -m pip install -r requirements.txt -q
    echo ✅ 依赖已安装
) else (
    echo ✅ 依赖已就绪
)

REM 检查 ADB
where adb >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo 📦 ADB 未找到，请安装: https://developer.android.com/studio/releases/platform-tools
    echo    然后将 platform-tools 目录添加到系统 PATH
) else (
    echo ✅ ADB 已就绪
)

echo.
echo 🚀 启动 Web 控制台...
echo   浏览器打开 http://localhost:8080
echo.

python main.py
pause
