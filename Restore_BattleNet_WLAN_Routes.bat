@echo off
chcp 65001 >nul
title 一键还原并清除战网无线分流网段路由 v1.4
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] 正在请求管理员权限以一键还原并清除全部战网 CIDR 网段路由...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
python -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" --restore
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
echo [OK] 已一键彻底还原全部战网无线 CIDR 网段路由与 Hosts 规则！
exit /b 0
