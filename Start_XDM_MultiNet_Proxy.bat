@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 西电双校园网 / 三通道 XDM 聚合下载本地代理 v1.2 (127.0.0.1:10880)

python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --status
echo.
echo ==========================================================================
echo   请选择操作或聚合加速模式 (直接回车默认选 1):
echo   [1] 后台静默开启/重启 三通道全开聚合 (无黑框后台常驻, 22~26 MB/s) [默认]
echo   [2] 前台启动三通道实时速率监控看板   (实时显示 有线v4/有线v6/无线v4 速率)
echo   [3] 后台开启 双网卡纯 IPv4 聚合模式  (有线IPv4 60%% + 无线IPv4 40%%)
echo   [4] 后台开启 单网线双栈聚合模式      (有线IPv4 50%% + 有线IPv6 50%%)
echo   [5] 开启 Windows 开机无感静默自启    (写入注册表 Run + 后台无黑框运行)
echo   [6] 关闭 Windows 开机自启
echo   [7] 停止正在运行的后台代理进程
echo ==========================================================================
set "CHOICE=1"
set /p "CHOICE=请输入选项编号 [1-7, 默认1]: "

if "%CHOICE%"=="1" (
    python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --start-bg --mode all
    pause
    exit /b 0
)
if "%CHOICE%"=="2" (
    python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --mode all
    pause
    exit /b 0
)
if "%CHOICE%"=="3" (
    python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --start-bg --mode dual-v4
    pause
    exit /b 0
)
if "%CHOICE%"=="4" (
    python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --start-bg --mode wired-dualstack
    pause
    exit /b 0
)
if "%CHOICE%"=="5" (
    python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --enable-autostart --mode all
    pause
    exit /b 0
)
if "%CHOICE%"=="6" (
    python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --disable-autostart
    pause
    exit /b 0
)
if "%CHOICE%"=="7" (
    python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --stop
    pause
    exit /b 0
)
python -X utf8 "%~dp0Xidian_MultiNet_Proxy.py" --start-bg --mode all
pause
