@echo off
chcp 65001 >nul 2>&1

net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
set "PY_EXE=python"
if exist "C:\Users\UserX\AppData\Local\Programs\Python\Python313\python.exe" set "PY_EXE=C:\Users\UserX\AppData\Local\Programs\Python\Python313\python.exe"

if /I "%~1"=="--restore" goto :ONE_CLICK_RESTORE
if /I "%~1"=="--disable" goto :ONE_CLICK_RESTORE
if /I "%~1"=="--disable-wlan" goto :ONE_CLICK_RESTORE
if /I "%~1"=="--clean" goto :ONE_CLICK_RESTORE
if /I "%~1"=="restore" goto :ONE_CLICK_RESTORE

"%PY_EXE%" -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" %*
exit /b %errorLevel%

:ONE_CLICK_RESTORE
"%PY_EXE%" -X utf8 "%~dp0BattleNet_WLAN_Accelerator.py" --restore
route delete 47.96.0.0 mask 255.252.0.0 >nul 2>&1
route delete 47.110.0.0 mask 255.254.0.0 >nul 2>&1
route delete 47.114.0.0 mask 255.254.0.0 >nul 2>&1
route delete 116.62.0.0 mask 255.255.0.0 >nul 2>&1
route delete 118.31.0.0 mask 255.255.0.0 >nul 2>&1
route delete 120.26.0.0 mask 255.254.0.0 >nul 2>&1
route delete 120.55.0.0 mask 255.255.0.0 >nul 2>&1
route delete 121.40.0.0 mask 255.252.0.0 >nul 2>&1
route delete 121.196.0.0 mask 255.252.0.0 >nul 2>&1
route delete 59.111.0.0 mask 255.255.0.0 >nul 2>&1
route delete 42.186.0.0 mask 255.255.0.0 >nul 2>&1
route delete 60.188.233.0 mask 255.255.255.0 >nul 2>&1
route delete 8.149.233.0 mask 255.255.255.0 >nul 2>&1
route delete 1.95.233.0 mask 255.255.255.0 >nul 2>&1
route delete 113.137.43.0 mask 255.255.255.0 >nul 2>&1
route delete 203.2.166.0 mask 255.255.255.0 >nul 2>&1
ipconfig /flushdns >nul 2>&1
exit /b 0
