@echo off
chcp 65001 >nul
title 西电校园网 Steam 三端超叠加 + 有线 IPv4 DPI 绕过引擎 v2.0

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] 正在请求管理员权限以启动本地 127.0.0.31~37:80 透明反向代理并注入 Hosts...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
:menu
cls
echo ==============================================================================
echo   西电校园网 Steam 三端超叠加 + 有线 IPv4 DPI 绕过快捷控制台 (v2.0)
echo   原理: 本地 127.0.0.31~37:80 按连接动态轮询 + 有线 IPv4 自动伪装 Mozilla/5.0
echo ==============================================================================
echo.
echo   [1] 一键后台开启：【三端超叠加模式 (40%%有线IPv6 + 30%%有线IPv4[DPI绕过] + 30%%无线IPv4)】
echo       (推荐！开启后可关闭此窗口，后台静默运行，最高可达 24~26+ MB/s)
echo.
echo   [2] 启动前台监控台：【三端超叠加实时速率看板 (实时显示三条通道分流网速)】
echo       (类似 XDM 代理监控台，窗口保持打开可实时查看三条物理链路吞吐量)
echo.
echo   [3] 一键后台开启：【单网线双栈叠加模式 (50%%有线IPv6 + 50%%有线IPv4[DPI绕过])】
echo       (未连接无线 Wi-Fi 时强烈推荐！仅靠一根网线即可突破百兆限制达到 ~21 MB/s)
echo.
echo   [4] 一键切换回：【双端免驻留模式 v1.2 (有线IPv6 + 无线IPv4 Mihomo隧道，无后台进程)】
echo.
echo   [5] 一键关闭并彻底清理所有配置与后台反代进程（恢复系统默认）
echo.
echo   [0] 退出
echo ==============================================================================
set /p choice=请输入选项编号 [0-5]: 

if "%choice%"=="1" (
    python "%~dp0Steam_DualStack_Optimizer.py" --apply-triplestack
    pause
    goto menu
)
if "%choice%"=="2" (
    python "%~dp0Steam_DualStack_Optimizer.py" --run-proxy-foreground --proxy-mode triplestack
    pause
    goto menu
)
if "%choice%"=="3" (
    python "%~dp0Steam_DualStack_Optimizer.py" --apply-wiredds
    pause
    goto menu
)
if "%choice%"=="4" (
    python "%~dp0Steam_DualStack_Optimizer.py" --apply-dualstack
    pause
    goto menu
)
if "%choice%"=="5" (
    python "%~dp0Steam_DualStack_Optimizer.py" --clear
    pause
    goto menu
)
if "%choice%"=="0" exit /b
goto menu
