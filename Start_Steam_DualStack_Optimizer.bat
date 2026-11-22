@echo off
chcp 65001 >nul
title 西电校园网 Steam 双栈/三端超叠加加速与 CDN 智能优选工具 v2.0

:: 自动检测并请求管理员权限 (用于更新系统 Hosts 与管理本地回环反代/静态路由)
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] 正在请求管理员权限以更新系统 Hosts 与网络加速规则...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
python "%~dp0Steam_DualStack_Optimizer.py" %*
