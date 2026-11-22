@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% equ 0 goto :ADMIN_OK
echo [UAC] Requesting Administrator privileges...
if "%~1"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
)
exit /b

:ADMIN_OK
chcp 65001 >nul 2>&1
title 西电双校园网 (CMCC_PPPOE + stu-xdwlan) 修复、保活与 IPv6 MTU 工具 v2.2

if /I "%~1"=="--auto-keep" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$mode='AUTO_KEEP'; $raw=[IO.File]::ReadAllText('%~f0',[Text.Encoding]::UTF8); $idx=$raw.LastIndexOf('# === PS_BODY ==='); Invoke-Expression $raw.Substring($idx)"
    exit /b
)

:MENU
cls
echo ============================================================================
echo        西电双校园网 ^(有线 CMCC_PPPOE + 无线 stu-xdwlan^) 综合管理工具 v2.2
echo ============================================================================
echo.
echo   [1] 一键修复双网卡并开启 xd-netkeeper 断线重连自动保活 ^(推荐^)
echo       - 修改 rasphone.pbk IpPrioritizeRemote=0 ^(阻止有线拨号锁死无线 WLAN^)
echo       - 注入有线 CMCC_PPPOE 默认路由 ^(Metric 10^) + 固化有线优先/无线兜底跃点数
echo       - 注册 RasClient 20225 事件触发器：用 xd-netkeeper 重连后自动恢复双网卡状态
echo.
echo   [2] 一键还原系统默认设置 ^(Restore Default^)
echo       - 还原 rasphone.pbk IpPrioritizeRemote=1 ^(恢复有线拨号单边接管默认行为^)
echo       - 卸载 xd-netkeeper 拨号重连保活计划任务 ^(DualCampusNet_PPPoE_AutoKeep^)
echo       - 还原 CMCC_PPPOE IPv6 MTU 为 1480，恢复自动跃点数，恢复「以太网」IPv4/IPv6 绑定
echo.
echo   [3] 运行双网卡分流 + IPv6 连通性全套自检 ^(6步诊断法^)
echo       - 检查网卡状态、路由表、计划任务、双源 IP 并发与 IPv6 连通性实测
echo.
echo   [4] 可选：单独调整有线 CMCC_PPPOE 的 IPv6 MTU ^(1280 / 1400 / 1480 默认^)
echo       - 当遇到跨网/海外 IPv6 大包黑洞时可调为 1400 或 1280；输入 1480 恢复默认
echo.
echo   [0] 退出程序 ^(Exit^)
echo.
echo ============================================================================
set "choice="
set /p "choice=请输入模式代号 [1 / 2 / 3 / 4 / 0] 并按回车: "

if "%choice%"=="1" goto MODE_REPAIR
if "%choice%"=="2" goto MODE_RESTORE
if "%choice%"=="3" goto MODE_TEST
if "%choice%"=="4" goto MODE_IPV6_MTU
if "%choice%"=="0" exit /b 0
echo [错误] 输入无效，请输入 1、2、3、4 或 0！
timeout /t 2 >nul
goto MENU

:MODE_REPAIR
echo.
echo [正在执行模式 1] 修复双校园网 + 注册 xd-netkeeper 重连自动保活...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$mode='1'; $raw=[IO.File]::ReadAllText('%~f0',[Text.Encoding]::UTF8); $idx=$raw.LastIndexOf('# === PS_BODY ==='); Invoke-Expression $raw.Substring($idx)"
echo.
pause
goto MENU

:MODE_RESTORE
echo.
echo [正在执行模式 2] 还原原系统默认设置 + 卸载重连保活任务 + 恢复以太网协议绑定...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$mode='2'; $raw=[IO.File]::ReadAllText('%~f0',[Text.Encoding]::UTF8); $idx=$raw.LastIndexOf('# === PS_BODY ==='); Invoke-Expression $raw.Substring($idx)"
echo.
pause
goto MENU

:MODE_TEST
echo.
echo [正在执行模式 3] 双网卡分流 + IPv6 全套实测...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$mode='3'; $raw=[IO.File]::ReadAllText('%~f0',[Text.Encoding]::UTF8); $idx=$raw.LastIndexOf('# === PS_BODY ==='); Invoke-Expression $raw.Substring($idx)"
echo.
pause
goto MENU

:MODE_IPV6_MTU
echo.
set "mtu_val="
set /p "mtu_val=请输入要设置的 CMCC_PPPOE IPv6 MTU 值 [1280 / 1400 / 1480(默认)]: "
if "%mtu_val%"=="" set "mtu_val=1480"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$mode='4'; $targetMtu='%mtu_val%'; $raw=[IO.File]::ReadAllText('%~f0',[Text.Encoding]::UTF8); $idx=$raw.LastIndexOf('# === PS_BODY ==='); Invoke-Expression $raw.Substring($idx)"
echo.
pause
goto MENU

# === PS_BODY ===
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$pbkPath = "$env:ProgramData\Microsoft\Network\Connections\Pbk\rasphone.pbk"
$taskName = "DualCampusNet_PPPoE_AutoKeep"
$keepScriptDir = "$env:ProgramData\DualCampusNet"
$keepScriptPath = "$keepScriptDir\pppoe_autokeep.ps1"
$mtuCfgPath = "$keepScriptDir\ipv6_mtu.txt"

function Get-ConfiguredIpv6Mtu() {
    if (Test-Path $mtuCfgPath) {
        $raw = ([System.IO.File]::ReadAllText($mtuCfgPath)).Trim()
        $val = 0
        if ([int]::TryParse($raw, [ref]$val) -and $val -ge 1280 -and $val -le 1500) {
            return $val
        }
    }
    return 0
}

function Apply-DualNicFix([bool]$Quiet = $false) {
    Set-NetIPInterface -InterfaceAlias "WLAN" -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 35 -ErrorAction SilentlyContinue
    $pppIpObj = Get-NetIPAddress -InterfaceAlias "CMCC_PPPOE" -AddressFamily IPv4 -ErrorAction SilentlyContinue
    if ($pppIpObj) {
        $ifIdx = $pppIpObj.InterfaceIndex
        $pppIp = $pppIpObj.IPAddress
        Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 15 -ErrorAction SilentlyContinue
        Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv6 -AutomaticMetric Disabled -InterfaceMetric 15 -ErrorAction SilentlyContinue
        & route.exe delete 0.0.0.0 mask 0.0.0.0 $pppIp if $ifIdx 2>$null | Out-Null
        & route.exe add 0.0.0.0 mask 0.0.0.0 $pppIp metric 10 if $ifIdx 2>$null | Out-Null
        $customMtu = Get-ConfiguredIpv6Mtu
        if ($customMtu -gt 0) {
            & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=$customMtu store=active 2>$null | Out-Null
            & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=$customMtu store=persistent 2>$null | Out-Null
            & netsh.exe interface ipv6 delete destinationcache interface=$ifIdx 2>$null | Out-Null
        }
        if (-not $Quiet) {
            Write-Host "  -> 已为 CMCC_PPPOE (IP=$pppIp, ifIndex=$ifIdx) 注入默认路由 (Metric 10)" -ForegroundColor Green
        }
    } else {
        if (-not $Quiet) {
            Write-Host "  [提示] 当前未检测到活动的 CMCC_PPPOE 连接；当您使用 xd-netkeeper 拨通后将由后台任务自动补注路由。" -ForegroundColor Yellow
        }
    }
}

if ($mode -eq 'AUTO_KEEP') {
    Start-Sleep -Milliseconds 1500
    Apply-DualNicFix -Quiet $true
    exit 0
}

if ($mode -eq '1') {
    Write-Host "[1/5] 正在修改拨号配置 rasphone.pbk (IpPrioritizeRemote=0)..." -ForegroundColor Cyan
    if (Test-Path $pbkPath) {
        Copy-Item -Path $pbkPath -Destination "$pbkPath.dualnet_bak" -Force -ErrorAction SilentlyContinue
        $rawPbk = [System.IO.File]::ReadAllText($pbkPath)
        [System.IO.File]::WriteAllText($pbkPath, ($rawPbk -replace 'IpPrioritizeRemote=1', 'IpPrioritizeRemote=0'))
        Write-Host "  -> 已设置 IpPrioritizeRemote=0" -ForegroundColor Green
    }

    Write-Host "[2/5] 正在关闭「以太网」无网关 IPv4/IPv6 协议绑定..." -ForegroundColor Cyan
    Disable-NetAdapterBinding -Name "以太网" -ComponentID ms_tcpip6,ms_tcpip -ErrorAction SilentlyContinue

    Write-Host "[3/5] 正在配置双网卡并发路由与跃点数..." -ForegroundColor Cyan
    Apply-DualNicFix -Quiet $false

    Write-Host "[4/5] 正在注册 xd-netkeeper / PPPoE 拨号重连自动保活计划任务 ($taskName)..." -ForegroundColor Cyan
    if (-not (Test-Path $keepScriptDir)) { New-Item -ItemType Directory -Path $keepScriptDir -Force | Out-Null }
    $autoKeepPs1 = @'
Start-Sleep -Milliseconds 1500
Set-NetIPInterface -InterfaceAlias "WLAN" -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 35 -ErrorAction SilentlyContinue
$pppIpObj = Get-NetIPAddress -InterfaceAlias "CMCC_PPPOE" -AddressFamily IPv4 -ErrorAction SilentlyContinue
if ($pppIpObj) {
    $ifIdx = $pppIpObj.InterfaceIndex
    $pppIp = $pppIpObj.IPAddress
    Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 15 -ErrorAction SilentlyContinue
    Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv6 -AutomaticMetric Disabled -InterfaceMetric 15 -ErrorAction SilentlyContinue
    & route.exe delete 0.0.0.0 mask 0.0.0.0 $pppIp if $ifIdx 2>$null | Out-Null
    & route.exe add 0.0.0.0 mask 0.0.0.0 $pppIp metric 10 if $ifIdx 2>$null | Out-Null
    $mtuCfg = "$env:ProgramData\DualCampusNet\ipv6_mtu.txt"
    if (Test-Path $mtuCfg) {
        $m = ([System.IO.File]::ReadAllText($mtuCfg)).Trim()
        if ($m -match '^\d+$') {
            & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=$m store=active 2>$null | Out-Null
            & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=$m store=persistent 2>$null | Out-Null
            & netsh.exe interface ipv6 delete destinationcache interface=$ifIdx 2>$null | Out-Null
        }
    }
}
'@
    [System.IO.File]::WriteAllText($keepScriptPath, $autoKeepPs1, [System.Text.Encoding]::UTF8)
    & schtasks.exe /Create /TN $taskName /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$keepScriptPath`"" /SC ONEVENT /EC Application /MO "*[System[Provider[@Name='RasClient'] and EventID=20225]]" /RU "SYSTEM" /RL HIGHEST /F 2>$null | Out-Null
    Write-Host "  -> 已注册 SYSTEM 级事件触发任务 [$taskName]（监听 RasClient EventID=20225）" -ForegroundColor Green
    Write-Host "     后续使用 D:\dsh\xd-netkeeper 重连有线后，1.5 秒内自动补注双网卡路由，保持双网卡在线！" -ForegroundColor Green

    Write-Host "[5/5] 当前状态汇总：" -ForegroundColor Cyan
    Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Select-Object ifIndex,InterfaceAlias,NextHop,RouteMetric,InterfaceMetric | Format-Table -AutoSize
    Write-Host "[完成] 模式 1 修复与重连保活配置完毕！" -ForegroundColor Green
}
elseif ($mode -eq '2') {
    Write-Host "[1/4] 正在卸载拨号重连保活计划任务 ($taskName)..." -ForegroundColor Cyan
    & schtasks.exe /Delete /TN $taskName /F 2>$null | Out-Null
    if (Test-Path $keepScriptPath) { Remove-Item -Path $keepScriptPath -Force -ErrorAction SilentlyContinue }
    if (Test-Path $mtuCfgPath) { Remove-Item -Path $mtuCfgPath -Force -ErrorAction SilentlyContinue }

    Write-Host "[2/4] 正在还原 rasphone.pbk (IpPrioritizeRemote=1)..." -ForegroundColor Cyan
    if (Test-Path $pbkPath) {
        $rawPbk = [System.IO.File]::ReadAllText($pbkPath)
        [System.IO.File]::WriteAllText($pbkPath, ($rawPbk -replace 'IpPrioritizeRemote=0', 'IpPrioritizeRemote=1'))
    }

    Write-Host "[3/4] 正在恢复「以太网」的 IPv4/IPv6 协议绑定..." -ForegroundColor Cyan
    Enable-NetAdapterBinding -Name "以太网" -ComponentID ms_tcpip6,ms_tcpip -ErrorAction SilentlyContinue

    Write-Host "[4/4] 正在恢复自动跃点数及默认 IPv6 MTU (1480)..." -ForegroundColor Cyan
    Set-NetIPInterface -InterfaceAlias "WLAN" -AddressFamily IPv4 -AutomaticMetric Enabled -ErrorAction SilentlyContinue
    Set-NetIPInterface -InterfaceAlias "WLAN" -AddressFamily IPv6 -AutomaticMetric Enabled -ErrorAction SilentlyContinue
    $pppIpObj = Get-NetIPAddress -InterfaceAlias "CMCC_PPPOE" -AddressFamily IPv4 -ErrorAction SilentlyContinue
    if ($pppIpObj) {
        $ifIdx = $pppIpObj.InterfaceIndex
        Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv4 -AutomaticMetric Enabled -ErrorAction SilentlyContinue
        Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv6 -AutomaticMetric Enabled -ErrorAction SilentlyContinue
        & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=1480 store=active 2>$null | Out-Null
        & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=1480 store=persistent 2>$null | Out-Null
        & netsh.exe interface ipv6 delete destinationcache interface=$ifIdx 2>$null | Out-Null
    }
    Write-Host "[完成] 已全部还原为系统原始默认设置！" -ForegroundColor Green
}
elseif ($mode -eq '3') {
    Write-Host "=== 步骤 1/6：检查双网卡 IP、IPv6 子接口 MTU 与跃点数 ===" -ForegroundColor Cyan
    & netsh.exe interface ipv6 show subinterfaces
    Get-NetIPInterface | Where-Object { $_.InterfaceAlias -in @('CMCC_PPPOE','WLAN','以太网') } | Select-Object ifIndex,InterfaceAlias,AddressFamily,ConnectionState,InterfaceMetric,AutomaticMetric | Format-Table -AutoSize

    Write-Host "=== 步骤 2/6：检查 IPv4 默认路由表 (0.0.0.0/0) ===" -ForegroundColor Cyan
    Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Select-Object ifIndex,InterfaceAlias,NextHop,RouteMetric,InterfaceMetric,@{Name='TotalMetric';Expression={$_.RouteMetric + $_.InterfaceMetric}} | Sort-Object TotalMetric | Format-Table -AutoSize

    Write-Host "=== 步骤 3/6：检查 xd-netkeeper 拨号重连自动保活任务状态 ===" -ForegroundColor Cyan
    $tk = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $taskFile = "$env:SystemRoot\System32\Tasks\$taskName"
    $taskFileExists = $false
    try { $taskFileExists = Test-Path $taskFile -ErrorAction Stop } catch [System.UnauthorizedAccessException] { $taskFileExists = $true } catch {}
    if ($tk) { Write-Host "  [PASS] 计划任务 [$taskName] 已就绪 (State=$($tk.State))" -ForegroundColor Green }
    elseif ($taskFileExists -and (Test-Path $keepScriptPath)) { Write-Host "  [PASS] 计划任务 [$taskName] (SYSTEM 级) 与保活脚本已就绪" -ForegroundColor Green }
    else { Write-Host "  [WARN] 计划任务 [$taskName] 尚未注册（请运行模式 1 注册）" -ForegroundColor Yellow }

    $pppIp = (Get-NetIPAddress -InterfaceAlias "CMCC_PPPOE" -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
    $wlanIp = (Get-NetIPAddress -InterfaceAlias "WLAN" -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress

    Write-Host "=== 步骤 4/6：强制指定源 IP 进行 Ping 连通性测试 ===" -ForegroundColor Cyan
    if ($pppIp) { & ping.exe -n 2 -w 2000 -S $pppIp 223.5.5.5 }
    if ($wlanIp) { & ping.exe -n 2 -w 2000 -S $wlanIp 223.5.5.5 }

    Write-Host "=== 步骤 5/6：强制绑定网卡源 IP 测试 HTTP 出口公网 IP ===" -ForegroundColor Cyan
    $defOut = (& curl.exe -4 -sS --max-time 4 http://ip.sb 2>&1) -join ''
    Write-Host "  [默认主路由出口]  -> 公网 IP: $($defOut.Trim())" -ForegroundColor Green
    if ($pppIp) {
        $pppOut = (& curl.exe -4 --interface $pppIp -sS --max-time 4 http://ip.sb 2>&1) -join ''
        Write-Host "  [有线 CMCC_PPPOE] -> 源 IP: $pppIp | 公网出口 IP: $($pppOut.Trim())" -ForegroundColor Green
    }
    if ($wlanIp) {
        $wlanOut = (& curl.exe -4 --interface $wlanIp -sS --max-time 4 http://ip.sb 2>&1) -join ''
        Write-Host "  [无线 stu-xdwlan] -> 源 IP: $wlanIp | 公网出口 IP: $($wlanOut.Trim())" -ForegroundColor Green
    }

    Write-Host "=== 步骤 6/6：测试有线 IPv6 连通性 (test-ipv6.com 节点) ===" -ForegroundColor Cyan
    $v6Test1 = (& curl.exe -6 -k -sS -o NUL -w "HTTP:%{http_code} TIME:%{time_total}s SIZE:%{size_download}" --max-time 4 "http://[2400:8905:e001:10b::6666]/ip/?callback=enz&size=1600" 2>&1) -join ' '
    $v6Test2 = (& curl.exe -6 -k -sS -o NUL -w "HTTP:%{http_code} TIME:%{time_total}s SIZE:%{size_download}" --max-time 4 "https://ipv6.test-ipv6.com/ip/?callback=enz&size=1600" 2>&1) -join ' '
    Write-Host "  [mtu1280.test-ipv6.com 1600B 响应测试] -> $v6Test1" -ForegroundColor Green
    Write-Host "  [ipv6.test-ipv6.com    1600B 响应测试] -> $v6Test2" -ForegroundColor Green
}
elseif ($mode -eq '4') {
    $mtuInt = 1480
    if ([int]::TryParse($targetMtu, [ref]$mtuInt)) {
        if ($mtuInt -lt 1280 -or $mtuInt -gt 1500) { $mtuInt = 1480 }
    }
    if (-not (Test-Path $keepScriptDir)) { New-Item -ItemType Directory -Path $keepScriptDir -Force | Out-Null }
    if ($mtuInt -eq 1480) {
        if (Test-Path $mtuCfgPath) { Remove-Item -Path $mtuCfgPath -Force -ErrorAction SilentlyContinue }
    } else {
        [System.IO.File]::WriteAllText($mtuCfgPath, "$mtuInt", [System.Text.Encoding]::UTF8)
    }
    $pppIpObj = Get-NetIPAddress -InterfaceAlias "CMCC_PPPOE" -AddressFamily IPv4 -ErrorAction SilentlyContinue
    if ($pppIpObj) {
        $ifIdx = $pppIpObj.InterfaceIndex
        & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=$mtuInt store=active
        & netsh.exe interface ipv6 set subinterface interface=$ifIdx mtu=$mtuInt store=persistent
        & netsh.exe interface ipv6 delete destinationcache interface=$ifIdx
        & netsh.exe interface ipv6 show subinterfaces
        Write-Host "  -> 已将 CMCC_PPPOE (ifIndex=$ifIdx) 的 IPv6 MTU 设为 $mtuInt" -ForegroundColor Green
    } else {
        Write-Host "  [错误] 当前未检测到 CMCC_PPPOE 连接！" -ForegroundColor Red
    }
}