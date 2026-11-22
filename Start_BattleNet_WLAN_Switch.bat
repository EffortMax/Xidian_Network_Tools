@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title 西电校园网 暴雪战网 / 炉石传说 / 守望先锋 无线网段路由分流控制器 v1.4

:: ============================================================================
:: 1. 检查管理员权限（向 Windows 内核路由表注入/一键还原 CIDR 网段静态路由及更新 Hosts 需要管理员权限）
:: ============================================================================
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] 正在请求管理员权限以注入或还原战网无线网卡 CIDR 网段静态路由...
    if "%~1"=="" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    exit /b
)

cd /d "%~dp0"

:: ============================================================================
:: 2. 支持命令行一键参数模式（如 Start_BattleNet_WLAN_Switch.bat --restore / --enable / --status）
:: ============================================================================
if /I "%~1"=="--restore" goto :ONE_CLICK_RESTORE
if /I "%~1"=="--disable" goto :ONE_CLICK_RESTORE
if /I "%~1"=="--disable-wlan" goto :ONE_CLICK_RESTORE
if /I "%~1"=="--clean" goto :ONE_CLICK_RESTORE
if /I "%~1"=="restore" goto :ONE_CLICK_RESTORE

if not "%~1"=="" (
    python -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" %*
    exit /b %errorLevel%
)

:: ============================================================================
:: 3. 交互式主控菜单（集成状态诊断、一键注入 CIDR 网段路由、一键还原全部网段路由）
:: ============================================================================
:MAIN_MENU
echo.
python -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" --status
echo ==============================================================================
echo   西电校园网 暴雪战网 / 炉石传说 / 守望先锋 无线网段分流批处理控制台 v1.4
echo ==============================================================================
echo     [1] 一键开启【战网 + 炉石传说 + 守望先锋 无线 CIDR 网段路由分流加速】
echo         ^(注入阿里云杭州/网易雷火对局集群网段路由 + Hosts 防劫持，绝不干扰有线拨号^)
echo     [2] 一键还原【彻底清除全部已注入的 CIDR 网段路由、单点路由与 Hosts 映射】
echo         ^(批处理原生兜底 + Python 状态库双向清理，一键恢复纯有线默认路由表^)
echo     [3] 状态诊断【重新核验系统路由表并实测战网登录^(:1119^)与炉石对局服^(:3724^)连通性】
echo     [4] 动态守护【前台启动炉石/守望匹配对局 IP 实时日志监控，新网段自动注入无线路由】
echo     [0] 退出
echo ==============================================================================
set "USR_CHOICE="
set /p "USR_CHOICE=请输入选项编号 [0-4]: "
if "%USR_CHOICE%"=="1" (
    echo.
    python -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" --enable-wlan
    echo.
    pause
    goto :MAIN_MENU
)
if "%USR_CHOICE%"=="2" (
    call :DO_RESTORE_ALL
    echo.
    pause
    goto :MAIN_MENU
)
if "%USR_CHOICE%"=="3" (
    goto :MAIN_MENU
)
if "%USR_CHOICE%"=="4" (
    echo.
    python -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" --watch-matchmaking
    goto :MAIN_MENU
)
if "%USR_CHOICE%"=="0" (
    exit /b 0
)
goto :MAIN_MENU

:ONE_CLICK_RESTORE
call :DO_RESTORE_ALL
exit /b 0

:: ============================================================================
:: 4. 批处理原生一键还原网段路由子程序（双重保障：Python 状态还原 + 原生 route delete 兜底）
:: ============================================================================
:DO_RESTORE_ALL
echo.
echo [*] 正在执行一键还原（清理全部已注入的战网/炉石对局集群 CIDR 网段路由、单点路由与 Hosts）...
python -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" --restore
:: 原生批处理兜底清理全部 16 个核心战网/网易雷火/阿里云杭州对局 CIDR 网段静态路由
for %%R in (
    "47.96.0.0:255.252.0.0"
    "47.110.0.0:255.254.0.0"
    "47.114.0.0:255.254.0.0"
    "116.62.0.0:255.255.0.0"
    "118.31.0.0:255.255.0.0"
    "120.26.0.0:255.254.0.0"
    "120.55.0.0:255.255.0.0"
    "121.40.0.0:255.252.0.0"
    "121.196.0.0:255.252.0.0"
    "59.111.0.0:255.255.0.0"
    "42.186.0.0:255.255.0.0"
    "60.188.233.0:255.255.255.0"
    "8.149.233.0:255.255.255.0"
    "1.95.233.0:255.255.255.0"
    "113.137.43.0:255.255.255.0"
    "203.2.166.0:255.255.255.0"
) do (
    for /f "tokens=1,2 delims=:" %%A in ("%%~R") do (
        route delete %%A mask %%B >nul 2>&1
    )
)
ipconfig /flushdns >nul 2>&1
echo [✓] 批处理一键还原执行完毕！
exit /b 0
