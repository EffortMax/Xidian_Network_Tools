@echo off
chcp 65001 >nul
title 注入战网与炉石对局集群无线网卡 CIDR 网段路由
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
route delete 47.96.0.0 mask 255.252.0.0 >nul 2>&1
route add 47.96.0.0 mask 255.252.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 47.110.0.0 mask 255.254.0.0 >nul 2>&1
route add 47.110.0.0 mask 255.254.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 47.114.0.0 mask 255.254.0.0 >nul 2>&1
route add 47.114.0.0 mask 255.254.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 116.62.0.0 mask 255.255.0.0 >nul 2>&1
route add 116.62.0.0 mask 255.255.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 118.31.0.0 mask 255.255.0.0 >nul 2>&1
route add 118.31.0.0 mask 255.255.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 120.26.0.0 mask 255.254.0.0 >nul 2>&1
route add 120.26.0.0 mask 255.254.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 120.55.0.0 mask 255.255.0.0 >nul 2>&1
route add 120.55.0.0 mask 255.255.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 121.40.0.0 mask 255.252.0.0 >nul 2>&1
route add 121.40.0.0 mask 255.252.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 121.196.0.0 mask 255.252.0.0 >nul 2>&1
route add 121.196.0.0 mask 255.252.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 59.111.0.0 mask 255.255.0.0 >nul 2>&1
route add 59.111.0.0 mask 255.255.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 42.186.0.0 mask 255.255.0.0 >nul 2>&1
route add 42.186.0.0 mask 255.255.0.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 60.188.233.0 mask 255.255.255.0 >nul 2>&1
route add 60.188.233.0 mask 255.255.255.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 8.149.233.0 mask 255.255.255.0 >nul 2>&1
route add 8.149.233.0 mask 255.255.255.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 1.95.233.0 mask 255.255.255.0 >nul 2>&1
route add 1.95.233.0 mask 255.255.255.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 113.137.43.0 mask 255.255.255.0 >nul 2>&1
route add 113.137.43.0 mask 255.255.255.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 203.2.166.0 mask 255.255.255.0 >nul 2>&1
route add 203.2.166.0 mask 255.255.255.0 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 113.137.43.176 >nul 2>&1
route add 113.137.43.176 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 116.62.121.9 >nul 2>&1
route add 116.62.121.9 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 118.31.18.157 >nul 2>&1
route add 118.31.18.157 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 203.2.166.78 >nul 2>&1
route add 203.2.166.78 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 203.2.166.79 >nul 2>&1
route add 203.2.166.79 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 203.2.166.89 >nul 2>&1
route add 203.2.166.89 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 203.2.166.90 >nul 2>&1
route add 203.2.166.90 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 47.114.126.40 >nul 2>&1
route add 47.114.126.40 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 59.111.21.224 >nul 2>&1
route add 59.111.21.224 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 61.134.51.19 >nul 2>&1
route add 61.134.51.19 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 8.149.233.11 >nul 2>&1
route add 8.149.233.11 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
route delete 84.53.172.96 >nul 2>&1
route add 84.53.172.96 mask 255.255.255.255 10.175.255.254 metric 5 if 17 >nul 2>&1
ipconfig /flushdns >nul 2>&1
echo [OK] 注入战网与炉石对局集群无线网卡 CIDR 网段路由 执行完成！
exit /b 0
