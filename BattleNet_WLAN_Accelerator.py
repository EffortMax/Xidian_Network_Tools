#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
BattleNet_WLAN_Accelerator.py — 西电校园网 暴雪战网 / 炉石传说 / 守望先锋 无线网卡(WLAN)分流控制器 v1.4
功能：
  1. 针对西电校园网有线 PPPoE (CMCC_PPPOE) 封锁战网登录网关 (:1119) 与炉石/守望先锋动态对局服务器 (:3724) 的问题，
     采用「战网/网易雷火/阿里云杭州对局集群 CIDR 网段级静态路由 + 战网域名单点路由 + 防劫持 Hosts + 实时对局日志动态路由守护」方案：
     - 保持系统默认路由 (0.0.0.0/0) 100% 走有线网卡 (CMCC_PPPOE)，绝不开启全局 TUN 劫持，绝不干扰信大锐捷 (XD-NetKeeper.exe) 在线心跳；
     - 将暴雪国服/网易雷火/阿里云杭州核心对局服务器网段 (47.96.0.0/14, 116.62.0.0/16, 118.31.0.0/16 等) 精准指向无线校园网 (WLAN, Metric=5)；
     - 自动扫描 G:\Hearthstone\Logs\*\GameNetLogger.log 中的 GotoGameServe 对局 IP，对未覆盖的新对局 IP 自动补充 /24 网段路由；
  2. 提供一键完整还原功能 (--disable / --disable-wlan / --clean)：
     - 遍历清除全部已注入的 CIDR 网段路由 (route delete <net> mask <mask>) 与 /32 主机路由；
     - 停止后台对局路由守护进程，清理系统 Hosts 中的战网锚点块，将 Clash 策略组恢复为默认有线直连，并校验零残留；
  3. 修复 cn.version.battlenet.com.cn 的 HTTPS (:443) TLS 证书校验问题：
     - 剔除证书不匹配的 59.111.19.33 节点，锁定真实有效证书节点 (8.149.233.11 / 47.114.126.40)，彻底消除 Schannel:36884 报错。
"""

from __future__ import annotations
import argparse
import concurrent.futures
import csv
import ctypes
import datetime as dt
import glob
import io
import ipaddress
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "battlenet_wlan_state.json")
HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
HOSTS_START = "# === XIDIAN_BATTLENET_WLAN_START ==="
HOSTS_END = "# === XIDIAN_BATTLENET_WLAN_END ==="


def _resolve_clash_dir() -> str:
    appdata = os.environ.get("APPDATA")
    if appdata:
        cand = os.path.join(appdata, "io.github.clash-verge-rev.clash-verge-rev")
        if os.path.isdir(cand):
            return cand
    users_dir = r"C:\Users"
    if os.path.isdir(users_dir):
        for name in os.listdir(users_dir):
            cand = os.path.join(users_dir, name, "AppData", "Roaming", "io.github.clash-verge-rev.clash-verge-rev")
            if os.path.isdir(cand):
                return cand
    return os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "io.github.clash-verge-rev.clash-verge-rev")


CLASH_DIR = _resolve_clash_dir()
CLASH_RUNTIME_YAML = os.path.join(CLASH_DIR, "clash-verge.yaml")
CLASH_CONFIG_YAML = os.path.join(CLASH_DIR, "config.yaml")
CLASH_VERGE_YAML = os.path.join(CLASH_DIR, "verge.yaml")

CLASH_INSTALL_DIR = r"D:\clash_verge"
MIHOMO_EXE = os.path.join(CLASH_INSTALL_DIR, "verge-mihomo.exe")
SERVICE_INSTALL_EXE = os.path.join(CLASH_INSTALL_DIR, "resources", "clash-verge-service-install.exe")
SERVICE_EXE = os.path.join(CLASH_INSTALL_DIR, "resources", "clash-verge-service.exe")
MIHOMO_PIPE = r"\\.\pipe\verge-mihomo"
SERVICE_PIPE = r"\\.\pipe\clash-verge-service"
SERVICE_MAGIC = "Like as the waves make towards the pebbl'd shore, So do our minutes hasten to their end;"

BNET_GROUP_NAME = "\U0001f3ae \u66b4\u96ea\u6218\u7f51\u4e0e\u5b88\u671b\u5148\u950b"
WLAN_PROXY_NAME = "\U0001f4f6 \u65e0\u7ebf\u6821\u56ed\u7f51\u76f4\u8fde(WLAN)"
WIRED_DIRECT_PROXY_NAME = "\U0001f310 \u6709\u7ebf\u5bbd\u5e26/\u9ed8\u8ba4\u76f4\u8fde(DIRECT)"

HEARTHSTONE_LOG_DIR = r"G:\Hearthstone\Logs"

BNET_DOMAINS = [
    "blzdist-phx.necdn.leihuo.netease.com",
    "blzdist-ow.necdn.leihuo.netease.com",
    "blzdist-hs.necdn.leihuo.netease.com",
    "cn.actual.battlenet.com.cn",
    "cn.patch.battlenet.com.cn",
    "cn.version.battlenet.com.cn",
    "cn.cdn.blizzard.cn",
    "level3.blizzard.com",
]

# 注意：cn.version.battlenet.com.cn 与 cn.patch.battlenet.com.cn 已剔除 59.111.19.33（其 443 端口证书 CN 不匹配会导致 Schannel:36884）
BNET_DEFAULT_CANDIDATES = {
    "blzdist-phx.necdn.leihuo.netease.com": ["113.137.43.176", "203.2.166.90", "61.134.51.19", "203.2.166.89"],
    "blzdist-ow.necdn.leihuo.netease.com": ["113.137.43.176", "203.2.166.90", "61.134.51.19", "203.2.166.79"],
    "blzdist-hs.necdn.leihuo.netease.com": ["113.137.43.176", "203.2.166.90", "61.134.51.19", "203.2.166.78"],
    "cn.actual.battlenet.com.cn": ["118.31.18.157", "116.62.121.9", "59.111.21.224"],
    "cn.patch.battlenet.com.cn": ["8.149.233.11", "47.114.126.40"],
    "cn.version.battlenet.com.cn": ["8.149.233.11", "47.114.126.40"],
    "cn.cdn.blizzard.cn": ["113.137.43.176", "203.2.166.90"],
    "level3.blizzard.com": ["113.137.43.176", "203.2.166.90", "84.53.172.96"],
}

BNET_TUNNEL_LOOPBACK = {
    "blzdist-phx.necdn.leihuo.netease.com": "127.0.0.11",
    "blzdist-ow.necdn.leihuo.netease.com": "127.0.0.11",
    "blzdist-hs.necdn.leihuo.netease.com": "127.0.0.11",
    "cn.cdn.blizzard.cn": "127.0.0.11",
    "level3.blizzard.com": "127.0.0.11",
    "cn.actual.battlenet.com.cn": "127.0.0.12",
    "cn.patch.battlenet.com.cn": "127.0.0.13",
    "cn.version.battlenet.com.cn": "127.0.0.13",
}

# 暴雪国服 / 网易雷火 / 阿里云华东1(杭州) 战网大厅与游戏对局服务器 (:3724 / :1119 / :26503+) 核心 CIDR 网段表
BNET_GAME_CIDRS: list[tuple[str, str, str, str]] = [
    ("47.96.0.0", "255.252.0.0", "47.96.0.0/14", "阿里云杭州 炉石/守望对局服集群A (含 47.97.160.102 / 47.97.166.186 / 47.98.141.122)"),
    ("47.110.0.0", "255.254.0.0", "47.110.0.0/15", "阿里云杭州 暴雪国服对局服集群B"),
    ("47.114.0.0", "255.254.0.0", "47.114.0.0/15", "阿里云华东 战网补丁与版本网关集群 (含 47.114.126.40)"),
    ("116.62.0.0", "255.255.0.0", "116.62.0.0/16", "阿里云杭州 战网登录与炉石对局服集群 (含 116.62.23.102 / 116.62.121.9)"),
    ("118.31.0.0", "255.255.0.0", "118.31.0.0/16", "阿里云杭州 战网 Aurora 登录与对局集群 (含 118.31.18.157)"),
    ("120.26.0.0", "255.254.0.0", "120.26.0.0/15", "阿里云杭州 暴雪国服对局支撑集群C"),
    ("120.55.0.0", "255.255.0.0", "120.55.0.0/16", "阿里云杭州 暴雪国服对局支撑集群D"),
    ("121.40.0.0", "255.252.0.0", "121.40.0.0/14", "阿里云杭州 暴雪国服对局支撑集群E"),
    ("121.196.0.0", "255.252.0.0", "121.196.0.0/14", "阿里云杭州 暴雪国服对局支撑集群F"),
    ("59.111.0.0", "255.255.0.0", "59.111.0.0/16", "网易杭州 BGP 核心机房 (雷火战网大厅/认证/社交)"),
    ("42.186.0.0", "255.255.0.0", "42.186.0.0/16", "网易杭州 BGP 游戏网关集群 (含 42.186.194.77)"),
    ("60.188.233.0", "255.255.255.0", "60.188.233.0/24", "暴雪国服战网 Web 认证专线 (含 60.188.233.223)"),
    ("8.149.233.0", "255.255.255.0", "8.149.233.0/24", "战网版本与补丁有效证书节点 (含 8.149.233.11)"),
    ("1.95.233.0", "255.255.255.0", "1.95.233.0/24", "战网与炉石国服数据接口节点 (含 1.95.233.187)"),
    ("113.137.43.0", "255.255.255.0", "113.137.43.0/24", "网易雷火暴雪 TACT CDN 陕西电信节点 (含 113.137.43.176)"),
    ("203.2.166.0", "255.255.255.0", "203.2.166.0/24", "网易雷火暴雪 TACT CDN 骨干节点 (含 203.2.166.78~90)"),
]

DEFAULT_MATCHMAKING_TEST_SERVERS = [
    ("116.62.23.102", 3724, "炉石传说国服杭州对局服 #1 (GotoGameServe)"),
    ("47.97.160.102", 3724, "炉石传说国服杭州对局服 #2 (GotoGameServe)"),
    ("47.97.166.186", 3724, "炉石传说国服杭州对局服 #3 (GotoGameServe)"),
    ("47.98.141.122", 3724, "炉石传说国服杭州对局服 #4 (GotoGameServe)"),
]


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def discover_game_server_ips_from_logs(log_root: str = HEARTHSTONE_LOG_DIR) -> list[tuple[str, int]]:
    """
    扫描 G:\\Hearthstone\\Logs\\*\\GameNetLogger.log 与 Net.log，提取历史及最新分配的对局服务器 IP:Port
    """
    found: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    if not os.path.isdir(log_root):
        return found

    patterns = [
        os.path.join(log_root, "Hearthstone_*", "GameNetLogger.log"),
        os.path.join(log_root, "GameNetLogger.log"),
        os.path.join(log_root, "Hearthstone_*", "Net.log"),
        os.path.join(log_root, "Net.log"),
    ]
    files: list[str] = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    files = sorted(set(files), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)

    re_goto = re.compile(r"GotoGameServe\(\)\s*-\s*address=\s*(\d+\.\d+\.\d+\.\d+):(\d+)")
    re_conn = re.compile(r"ConnectAurora\(\)\s*-\s*address=\s*(\d+\.\d+\.\d+\.\d+):(\d+)")

    for fp in files[:25]:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            for m in re_goto.finditer(text):
                item = (m.group(1), int(m.group(2)))
                if item not in seen:
                    seen.add(item)
                    found.append(item)
            for m in re_conn.finditer(text):
                item = (m.group(1), int(m.group(2)))
                if item not in seen:
                    seen.add(item)
                    found.append(item)
        except Exception:
            pass
    return found


def is_ip_covered_by_cidrs(ip_str: str, cidr_list: list[tuple[str, str, str, str]]) -> str | None:
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        for _net, _mask, cidr_str, _desc in cidr_list:
            if ip_obj in ipaddress.ip_network(cidr_str, strict=False):
                return cidr_str
    except Exception:
        pass
    return None


def build_full_cidr_plan() -> tuple[list[tuple[str, str, str, str]], list[tuple[str, int]]]:
    """
    返回完整的待注入 CIDR 网段列表（内置核心网段 + 从炉石日志自动学习补充的 /24 网段）以及扫描到的对局服列表
    """
    plan = list(BNET_GAME_CIDRS)
    discovered = discover_game_server_ips_from_logs()
    for ip_str, port in discovered:
        if ip_str.startswith(("127.", "10.", "192.168.", "172.16.")):
            continue
        if not is_ip_covered_by_cidrs(ip_str, plan):
            parts = ip_str.split(".")
            if len(parts) == 4:
                net = f"{parts[0]}.{parts[1]}.{parts[2]}.0"
                mask = "255.255.255.0"
                cidr = f"{net}/24"
                desc = f"炉石日志自动学习对局网段 (源自 {ip_str}:{port})"
                plan.append((net, mask, cidr, desc))
    return plan, discovered


def get_active_route_table_text() -> str:
    try:
        p = subprocess.run(["route", "print", "-4"], capture_output=True, text=True, encoding="gbk", errors="replace", timeout=6)
        return p.stdout or ""
    except Exception:
        return ""


def verify_cidr_routes_in_os_table(cidr_plan: list[tuple[str, str, str, str]], wlan_gw: str | None = None) -> list[dict]:
    """
    直接读取 Windows 内核 IPv4 路由表 (route print -4)，核实每条 CIDR 网段路由是否真实存在于系统路由表中
    """
    rt_text = get_active_route_table_text()
    results = []
    for net, mask, cidr, desc in cidr_plan:
        # 匹配形如: 47.96.0.0    255.252.0.0    10.175.255.254   10.175.75.166    5
        pat = re.compile(rf"^\s*{re.escape(net)}\s+{re.escape(mask)}\s+(\S+)\s+(\S+)\s+(\d+)", re.MULTILINE)
        m = pat.search(rt_text)
        if m:
            nh, iface, metric = m.group(1), m.group(2), m.group(3)
            ok = True if not wlan_gw else (nh == wlan_gw or iface.startswith("10.175."))
            results.append({
                "net": net,
                "mask": mask,
                "cidr": cidr,
                "desc": desc,
                "present": ok,
                "gateway": nh,
                "interface": iface,
                "metric": int(metric) if metric.isdigit() else metric,
            })
        else:
            results.append({
                "net": net,
                "mask": mask,
                "cidr": cidr,
                "desc": desc,
                "present": False,
                "gateway": None,
                "interface": None,
                "metric": None,
            })
    return results


def run_elevated_route_commands(commands: list[list[str]], op_title: str = "更新战网无线分流路由表", script_name: str = "Apply_BattleNet_WLAN_Routes.bat") -> bool:
    """
    当当前进程已是管理员权限（如从 Start_BattleNet_WLAN_Switch.bat 启动）时，直接在当前进程内快速执行所有 route 命令；
    当当前进程非管理员权限时，生成持久化批处理脚本并通过 Start-Process -Verb RunAs 请求 UAC 提权执行。
    """
    if not commands:
        return True

    bat_path = os.path.join(HERE, script_name)
    try:
        lines = [
            "@echo off",
            "chcp 65001 >nul 2>&1",
            "title BattleNet_WLAN_CIDR_Route_Controller_v1.4",
            "net session >nul 2>&1",
            "if %errorLevel% neq 0 (",
            "    powershell -NoProfile -Command \"Start-Process -FilePath '%~f0' -Verb RunAs\"",
            "    exit /b",
            ")",
        ]
        for cmd in commands:
            quoted = " ".join(f'"{c}"' if " " in c else c for c in cmd)
            lines.append(f"{quoted} >nul 2>&1")
        lines.append("ipconfig /flushdns >nul 2>&1")
        lines.append("echo [OK] BattleNet WLAN CIDR routes updated successfully.")
        lines.append("exit /b 0")
        with open(bat_path, "w", encoding="utf-8", newline="") as f:
            f.write("\r\n".join(lines) + "\r\n")
    except Exception:
        pass

    if is_admin():
        ok_any = False
        for cmd in commands:
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode == 0:
                ok_any = True
        return ok_any

    try:
        print(f"[*] 当前终端非管理员权限，正在请求管理员权限 (UAC) 批量执行 {len(commands)} 条路由表操作 ({script_name})...")
        ps_cmd = (
            f"$p = Start-Process -FilePath '{bat_path}' -Verb RunAs -PassThru; "
            f"if ($p) {{ $p.WaitForExit(15000) | Out-Null }}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            timeout=18,
        )
        return True
    except Exception:
        print(f"[*] UAC 提权窗口已拉起或待确认，您也可随时双击运行 {script_name} 或 Start_BattleNet_WLAN_Switch.bat。")
        return False


def check_mihomo_elevation(image_name: str = "verge-mihomo.exe") -> dict:
    """检查当前运行的 verge-mihomo.exe 是否具备管理员/系统服务(Session 0)权限"""
    try:
        p = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        pids = []
        for row in csv.reader(io.StringIO(p.stdout or "")):
            if len(row) >= 2 and row[0].strip().lower() == image_name.lower():
                try:
                    pids.append((int(row[1]), row[2].strip() if len(row) > 2 else ""))
                except ValueError:
                    pass
        if not pids:
            return {"running": False, "elevated": False, "pid": None, "mode": "stopped"}

        pid, session_name = pids[0]
        if session_name.lower() == "services":
            return {"running": True, "elevated": True, "pid": pid, "mode": "service"}

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        TOKEN_QUERY = 0x0008
        TokenElevation = 20
        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32

        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            err = ctypes.GetLastError()
            return {
                "running": True,
                "elevated": (err == 5),
                "pid": pid,
                "mode": "elevated_admin" if err == 5 else f"proc_err_{err}",
            }
        try:
            h_tok = ctypes.c_void_p()
            if not advapi32.OpenProcessToken(h_proc, TOKEN_QUERY, ctypes.byref(h_tok)):
                err = ctypes.GetLastError()
                return {
                    "running": True,
                    "elevated": (err == 5),
                    "pid": pid,
                    "mode": "elevated_admin" if err == 5 else f"tok_err_{err}",
                }
            try:
                elev = ctypes.c_ulong(0)
                ret_len = ctypes.c_ulong(0)
                if advapi32.GetTokenInformation(
                    h_tok, TokenElevation, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(ret_len)
                ):
                    is_elev = bool(elev.value)
                    return {
                        "running": True,
                        "elevated": is_elev,
                        "pid": pid,
                        "mode": "elevated_sidecar" if is_elev else "unelevated_sidecar",
                    }
            finally:
                kernel32.CloseHandle(h_tok)
        finally:
            kernel32.CloseHandle(h_proc)
        return {"running": True, "elevated": False, "pid": pid, "mode": "unknown"}
    except Exception as e:
        return {"running": False, "elevated": False, "pid": None, "mode": f"error:{e}"}


def detect_tun_adapter() -> dict:
    """检测 Windows 系统中真实的 Wintun / Clash / Meta 虚拟网卡接口是否已创建并处于 connected 状态"""
    res = {"up": False, "name": None, "ifIndex": None, "ip": None, "state": "absent"}
    try:
        p = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "interfaces"],
            capture_output=True, text=True, errors="replace", timeout=5
        )
        for line in (p.stdout or "").splitlines():
            m = re.match(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*$", line)
            if not m:
                continue
            idx_s, _met, _mtu, state_s, name_s = m.groups()
            if re.search(r"^(Meta|Clash|Mihomo|verge-tun|utun|wintun)", name_s, re.IGNORECASE):
                is_conn = state_s.lower() in ("connected", "已连接")
                res["name"] = name_s
                res["ifIndex"] = int(idx_s)
                res["state"] = state_s
                res["up"] = is_conn
                break

        p_ip = subprocess.run(
            ["ipconfig"], capture_output=True, text=True, errors="replace", timeout=5
        )
        ip_out = p_ip.stdout or ""
        if "198.18.0.1" in ip_out:
            res["ip"] = "198.18.0.1"
            res["up"] = True
            if not res["name"]:
                res["name"] = "Meta"
                res["state"] = "connected"
        elif res["up"]:
            blocks = re.split(r"\r?\n(?=\S)", ip_out)
            for blk in blocks:
                if res["name"] and res["name"].lower() in blk.lower():
                    m_ip = re.search(r"(?:IPv4|IP Address)[^:]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", blk, re.I)
                    if m_ip:
                        res["ip"] = m_ip.group(1)
    except Exception as e:
        res["error"] = str(e)
    return res


def detect_network_interfaces() -> dict:
    """同时检测有线宽带 (CMCC_PPPOE / 以太网) 与无线网卡 (WLAN) 的实时连接状态"""
    ps = r"""
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $all = Get-NetIPConfiguration | Where-Object { $_.IPv4Address -ne $null }
    $wlan = $all | Where-Object { $_.InterfaceAlias -match 'WLAN|Wi-Fi|无线' } | Select-Object -First 1
    $pppoe = $all | Where-Object { $_.InterfaceAlias -match 'PPPOE|宽带|CMCC' } | Select-Object -First 1
    $defaultRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
    [PSCustomObject]@{
        wlan = if ($wlan) {
            @{
                ok = $true
                alias = $wlan.InterfaceAlias
                ifIndex = [int]$wlan.InterfaceIndex
                ip = $wlan.IPv4Address[0].IPAddress
                gw = if ($wlan.IPv4DefaultGateway) { $wlan.IPv4DefaultGateway[0].NextHop } else { "10.175.255.254" }
            }
        } else { @{ ok = $false } }
        pppoe = if ($pppoe) {
            @{
                ok = $true
                alias = $pppoe.InterfaceAlias
                ifIndex = [int]$pppoe.InterfaceIndex
                ip = $pppoe.IPv4Address[0].IPAddress
            }
        } else { @{ ok = $false } }
        defaultIfIndex = if ($defaultRoute) { [int]$defaultRoute.InterfaceIndex } else { -1 }
    } | ConvertTo-Json -Compress -Depth 4
    """
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            encoding="utf-8", errors="replace", timeout=8
        ).strip()
        return json.loads(out)
    except Exception as e:
        return {"wlan": {"ok": False, "error": str(e)}, "pppoe": {"ok": False}, "defaultIfIndex": -1}


def detect_wlan_interface() -> dict:
    info = detect_network_interfaces()
    return info.get("wlan") or {"ok": False}


def dns_query_via_wlan(domain: str, wlan_ip: str, dns_server: str = "223.5.5.5") -> list[str]:
    try:
        tid = 0x424E
        flags = 0x0100
        header = struct.pack(">HHHHHH", tid, flags, 1, 0, 0, 0)
        qname = b"".join(struct.pack("B", len(p)) + p.encode("ascii") for p in domain.split(".")) + b"\x00"
        question = qname + struct.pack(">HH", 1, 1)
        pkt = header + question

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.5)
        s.bind((wlan_ip, 0))
        s.sendto(pkt, (dns_server, 53))
        resp, _ = s.recvfrom(1024)
        s.close()

        ancount = struct.unpack(">H", resp[6:8])[0]
        offset = len(pkt)
        ips = []
        for _ in range(ancount):
            if offset >= len(resp):
                break
            if (resp[offset] & 0xC0) == 0xC0:
                offset += 2
            else:
                while offset < len(resp) and resp[offset] != 0:
                    offset += 1 + resp[offset]
                offset += 1
            rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", resp[offset:offset + 10])
            offset += 10
            if rtype == 1 and rdlen == 4:
                ip = socket.inet_ntoa(resp[offset:offset + 4])
                if ip not in ("219.145.171.39", "59.111.19.33") and ip not in ips:
                    ips.append(ip)
            offset += rdlen
        return ips
    except Exception:
        return []


def probe_bnet_node(ip: str, host: str, wlan_ip: str | None = None, port: int = 80) -> float:
    t0 = time.perf_counter()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.8)
    try:
        if wlan_ip:
            s.bind((wlan_ip, 0))
        s.connect((ip, port))
        if port == 443:
            ctx = ssl.create_default_context()
            ss = ctx.wrap_socket(s, server_hostname=host)
            ss.close()
            return round((time.perf_counter() - t0) * 1000.0, 1)
        if port == 80 and "blzdist" in host:
            req = (
                f"GET /tpr/catalogs/data/b2/81/b28162fb26a1983f3d33b4fe8ef0b829 HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"User-Agent: Battle.net/2.53.8.17986\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("ascii")
            s.sendall(req)
            data = s.recv(256)
            if not data or b"HTTP/1." not in data:
                return -1.0
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return round(dt_ms, 1)
    except Exception:
        return -1.0
    finally:
        try:
            s.close()
        except Exception:
            pass


def mihomo_pipe_request(method: str, path: str, body_dict: dict | None = None) -> tuple[int, str]:
    body_bytes = json.dumps(body_dict, ensure_ascii=False).encode("utf-8") if body_dict is not None else b""
    headers = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer set-your-secret\r\n"
    if body_bytes:
        headers += f"Content-Type: application/json\r\nContent-Length: {len(body_bytes)}\r\n"
    headers += "Connection: close\r\n\r\n"
    req_bytes = headers.encode("utf-8") + body_bytes
    try:
        with open(MIHOMO_PIPE, "r+b", buffering=0) as pipe:
            pipe.write(req_bytes)
            raw_bytes = pipe.read(65536)
        raw = raw_bytes.decode("utf-8", errors="replace")
        first_line = raw.splitlines()[0] if raw else ""
        m = re.search(r"HTTP/1\.[01]\s+(\d+)", first_line)
        code = int(m.group(1)) if m else 0
        body = raw.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in raw else raw.split("\n\n", 1)[-1]
        return code, body.strip()
    except Exception as e:
        return 0, str(e)


def _update_yaml_tun_section(yaml_path: str, enable: bool, stack: str = "mixed") -> bool:
    if not os.path.exists(yaml_path):
        return False
    try:
        raw = open(yaml_path, encoding="utf-8", errors="replace").read()
        lines = raw.splitlines()
        out = []
        in_tun = False
        found_tun = False
        wrote_enable = False
        wrote_stack = False
        enable_str = "true" if enable else "false"

        for line in lines:
            if re.match(r"^tun:\s*$", line):
                in_tun = True
                found_tun = True
                out.append(line)
                continue
            if in_tun:
                if re.match(r"^[a-zA-Z0-9_-]+:", line):
                    if not wrote_enable:
                        out.append(f"  enable: {enable_str}")
                        wrote_enable = True
                    if not wrote_stack:
                        out.append(f"  stack: {stack}")
                        wrote_stack = True
                    in_tun = False
                else:
                    if re.match(r"^\s+enable:\s*", line):
                        out.append(f"  enable: {enable_str}")
                        wrote_enable = True
                        continue
                    if re.match(r"^\s+stack:\s*", line):
                        out.append(f"  stack: {stack}")
                        wrote_stack = True
                        continue
            out.append(line)

        if in_tun:
            if not wrote_enable:
                out.append(f"  enable: {enable_str}")
            if not wrote_stack:
                out.append(f"  stack: {stack}")

        if not found_tun:
            out.extend([
                "tun:",
                f"  enable: {enable_str}",
                f"  stack: {stack}",
                "  auto-route: true",
                "  strict-route: false",
                "  auto-detect-interface: false",
                "  dns-hijack:",
                "  - any:53",
            ])

        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        return True
    except Exception:
        return False


def sync_tun_yaml_config(enable: bool, stack: str = "mixed") -> None:
    _update_yaml_tun_section(CLASH_RUNTIME_YAML, enable, stack=stack)
    _update_yaml_tun_section(CLASH_CONFIG_YAML, enable, stack=stack)
    if os.path.exists(CLASH_VERGE_YAML):
        try:
            v_raw = open(CLASH_VERGE_YAML, encoding="utf-8", errors="replace").read()
            enable_str = "true" if enable else "false"
            if re.search(r"^enable_tun_mode:\s*\S+", v_raw, flags=re.MULTILINE):
                v_raw = re.sub(
                    r"^enable_tun_mode:\s*\S+",
                    f"enable_tun_mode: {enable_str}",
                    v_raw,
                    flags=re.MULTILINE,
                )
            else:
                v_raw = v_raw.rstrip() + f"\nenable_tun_mode: {enable_str}\n"
            with open(CLASH_VERGE_YAML, "w", encoding="utf-8") as f:
                f.write(v_raw)
        except Exception:
            pass


def set_mihomo_bnet_group(target_proxy: str) -> bool:
    enc_group = urllib.parse.quote(BNET_GROUP_NAME)
    code, _ = mihomo_pipe_request("PUT", f"/proxies/{enc_group}", {"name": target_proxy})
    if code not in (200, 204) and target_proxy == WIRED_DIRECT_PROXY_NAME:
        code, _ = mihomo_pipe_request("PUT", f"/proxies/{enc_group}", {"name": "DIRECT"})
    return code in (200, 204)


def ensure_tun_disabled_safe() -> bool:
    """确保全局 TUN 虚拟网卡处于关闭状态，防止劫持 0.0.0.0/0 导致有线 CMCC_PPPOE 与信大锐捷断联"""
    sync_tun_yaml_config(False, stack="mixed")
    code, _ = mihomo_pipe_request("PATCH", "/configs", {"tun": {"enable": False}})
    return code in (200, 204)


def ensure_mihomo_bnet_tunnels(tact_ip: str, aurora_ip: str, patch_ip: str) -> bool:
    """
    在 clash-verge.yaml 中无损更新/注入 127.0.0.11~13 战网本地无线透明隧道并热重载：
    其中 127.0.0.13:443 严格指向具备合法 cn.version.battlenet.com.cn 证书的 patch_ip (8.149.233.11 / 47.114.126.40)。
    """
    if not os.path.exists(CLASH_RUNTIME_YAML):
        return False
    try:
        raw = open(CLASH_RUNTIME_YAML, encoding="utf-8", errors="replace").read()
        raw = re.sub(r"\n?# === BNET_TUNNELS_START ===.*?# === BNET_TUNNELS_END ===\n?", "\n", raw, flags=re.DOTALL)

        bnet_items_lines = [
            f"- name: bnet-tact-80\n  type: tunnel\n  port: 80\n  listen: 127.0.0.11\n  network:\n  - tcp\n  target: {tact_ip}:80\n  proxy: {BNET_GROUP_NAME}",
            f"- name: bnet-tact-443\n  type: tunnel\n  port: 443\n  listen: 127.0.0.11\n  network:\n  - tcp\n  target: {tact_ip}:443\n  proxy: {BNET_GROUP_NAME}",
            f"- name: bnet-aurora-1119\n  type: tunnel\n  port: 1119\n  listen: 127.0.0.12\n  network:\n  - tcp\n  - udp\n  target: {aurora_ip}:1119\n  proxy: {BNET_GROUP_NAME}",
            f"- name: bnet-aurora-443\n  type: tunnel\n  port: 443\n  listen: 127.0.0.12\n  network:\n  - tcp\n  target: {aurora_ip}:443\n  proxy: {BNET_GROUP_NAME}",
            f"- name: bnet-patch-1119\n  type: tunnel\n  port: 1119\n  listen: 127.0.0.13\n  network:\n  - tcp\n  - udp\n  target: {patch_ip}:1119\n  proxy: {BNET_GROUP_NAME}",
            f"- name: bnet-patch-80\n  type: tunnel\n  port: 80\n  listen: 127.0.0.13\n  network:\n  - tcp\n  target: {patch_ip}:80\n  proxy: {BNET_GROUP_NAME}",
            f"- name: bnet-patch-443\n  type: tunnel\n  port: 443\n  listen: 127.0.0.13\n  network:\n  - tcp\n  target: {patch_ip}:443\n  proxy: {BNET_GROUP_NAME}",
        ]

        lines = raw.splitlines()
        listeners_start = None
        listeners_end = None
        for idx, line in enumerate(lines):
            if re.match(r"^listeners:\s*$", line):
                listeners_start = idx
                for j in range(idx + 1, len(lines)):
                    if re.match(r"^[a-zA-Z0-9_-]+:", lines[j]):
                        listeners_end = j
                        break
                if listeners_end is None:
                    listeners_end = len(lines)
                break

        if listeners_start is not None and listeners_end is not None:
            existing_block = lines[listeners_start + 1 : listeners_end]
            kept_items: list[list[str]] = []
            cur_item: list[str] = []
            for b_line in existing_block:
                if b_line.strip().startswith("#"):
                    continue
                if re.match(r"^-\s+name:\s*", b_line):
                    if cur_item:
                        first_m = re.match(r"^-\s+name:\s*(\S+)", cur_item[0])
                        item_name = first_m.group(1) if first_m else ""
                        if not item_name.startswith("bnet-"):
                            kept_items.append(cur_item)
                    cur_item = [b_line]
                else:
                    if cur_item:
                        cur_item.append(b_line)
            if cur_item:
                first_m = re.match(r"^-\s+name:\s*(\S+)", cur_item[0])
                item_name = first_m.group(1) if first_m else ""
                if not item_name.startswith("bnet-"):
                    kept_items.append(cur_item)

            new_listener_lines = ["listeners:"]
            for entry in bnet_items_lines:
                new_listener_lines.extend(entry.splitlines())
            for k_item in kept_items:
                new_listener_lines.extend(k_item)

            new_lines = lines[:listeners_start] + new_listener_lines + lines[listeners_end:]
        else:
            new_listener_lines = ["listeners:"]
            for entry in bnet_items_lines:
                new_listener_lines.extend(entry.splitlines())
            insert_pos = len(lines)
            for idx, line in enumerate(lines):
                if re.match(r"^proxies:\s*$", line):
                    insert_pos = idx
                    break
            new_lines = lines[:insert_pos] + new_listener_lines + lines[insert_pos:]

        with open(CLASH_RUNTIME_YAML, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")

        prof_dir = os.path.join(CLASH_DIR, "profiles")
        if os.path.isdir(prof_dir):
            js_bnet_array = (
                f"  const bnetTunnels = [\n"
                f"    {{ name: \"bnet-tact-80\", type: \"tunnel\", port: 80, listen: \"127.0.0.11\", network: [\"tcp\"], target: \"{tact_ip}:80\", proxy: \"{BNET_GROUP_NAME}\" }},\n"
                f"    {{ name: \"bnet-tact-443\", type: \"tunnel\", port: 443, listen: \"127.0.0.11\", network: [\"tcp\"], target: \"{tact_ip}:443\", proxy: \"{BNET_GROUP_NAME}\" }},\n"
                f"    {{ name: \"bnet-aurora-1119\", type: \"tunnel\", port: 1119, listen: \"127.0.0.12\", network: [\"tcp\", \"udp\"], target: \"{aurora_ip}:1119\", proxy: \"{BNET_GROUP_NAME}\" }},\n"
                f"    {{ name: \"bnet-aurora-443\", type: \"tunnel\", port: 443, listen: \"127.0.0.12\", network: [\"tcp\"], target: \"{aurora_ip}:443\", proxy: \"{BNET_GROUP_NAME}\" }},\n"
                f"    {{ name: \"bnet-patch-1119\", type: \"tunnel\", port: 1119, listen: \"127.0.0.13\", network: [\"tcp\", \"udp\"], target: \"{patch_ip}:1119\", proxy: \"{BNET_GROUP_NAME}\" }},\n"
                f"    {{ name: \"bnet-patch-80\", type: \"tunnel\", port: 80, listen: \"127.0.0.13\", network: [\"tcp\"], target: \"{patch_ip}:80\", proxy: \"{BNET_GROUP_NAME}\" }},\n"
                f"    {{ name: \"bnet-patch-443\", type: \"tunnel\", port: 443, listen: \"127.0.0.13\", network: [\"tcp\"], target: \"{patch_ip}:443\", proxy: \"{BNET_GROUP_NAME}\" }}\n"
                f"  ];"
            )
            for fn in os.listdir(prof_dir):
                if fn.endswith(".js"):
                    fp = os.path.join(prof_dir, fn)
                    try:
                        js_raw = open(fp, encoding="utf-8").read()
                        if "const bnetTunnels = [" in js_raw:
                            js_new = re.sub(
                                r"  const bnetTunnels = \[.*?\];",
                                js_bnet_array,
                                js_raw,
                                flags=re.DOTALL,
                            )
                            if js_new != js_raw:
                                open(fp, "w", encoding="utf-8").write(js_new)
                        elif "bnet-tact-80" not in js_raw and "  return config;" in js_raw:
                            js_snip = (
                                "  if (!Array.isArray(config.listeners)) config.listeners = [];\n"
                                + js_bnet_array
                                + "\n  for (const t of bnetTunnels) { const idx = config.listeners.findIndex(x => x && x.name === t.name); if (idx >= 0) config.listeners[idx] = t; else config.listeners.push(t); }\n  return config;"
                            )
                            open(fp, "w", encoding="utf-8").write(js_raw.replace("  return config;", js_snip))
                    except Exception:
                        pass

        code, _ = mihomo_pipe_request("PUT", "/configs?force=true", {"path": CLASH_RUNTIME_YAML})
        return code in (200, 204)
    except Exception:
        return False


def get_mihomo_status() -> dict:
    enc_group = urllib.parse.quote(BNET_GROUP_NAME)
    code1, body1 = mihomo_pipe_request("GET", f"/proxies/{enc_group}")
    code2, body2 = mihomo_pipe_request("GET", "/configs")
    elev = check_mihomo_elevation()
    tun_adapter = detect_tun_adapter()
    res = {
        "running": code1 == 200 or code2 == 200,
        "group_now": None,
        "tun_config_enable": None,
        "tun_enable": False,
        "tun_stack": None,
        "tun_adapter": tun_adapter,
        "elevation": elev,
    }
    if code1 == 200:
        try:
            d1 = json.loads(body1)
            res["group_now"] = d1.get("now")
            res["group_all"] = d1.get("all")
        except Exception:
            pass
    if code2 == 200:
        try:
            d2 = json.loads(body2)
            tun = d2.get("tun") or {}
            res["tun_config_enable"] = bool(tun.get("enable"))
            res["tun_stack"] = tun.get("stack")
            res["tun_enable"] = bool(res["tun_config_enable"] and tun_adapter.get("up"))
        except Exception:
            pass
    return res


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(st: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def stop_matchmaking_guard_if_running(st: dict | None = None) -> bool:
    if st is None:
        st = load_state()
    pid = st.get("watch_pid")
    if not pid:
        return False
    try:
        r = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def clean_previous_injection(verbose: bool = False, allow_elevate: bool = True) -> tuple[int, int, bool]:
    """
    一键清理并还原全部已注入的 CIDR 网段路由、/32 主机路由与 Hosts 锚点块：
    返回: (deleted_cidr_count, deleted_host_count, hosts_cleaned)
    """
    st = load_state()
    stop_matchmaking_guard_if_running(st)

    # 1. 汇总需要清除的所有 CIDR 网段路由（内置网段表 + 状态文件记录的动态网段）
    cidr_targets: dict[tuple[str, str], str] = {}
    for net, mask, cidr, _desc in BNET_GAME_CIDRS:
        cidr_targets[(net, mask)] = cidr
    for item in st.get("injected_cidr_routes") or []:
        if isinstance(item, dict) and item.get("net") and item.get("mask"):
            cidr_targets[(item["net"], item["mask"])] = item.get("cidr", f"{item['net']}/{item['mask']}")

    # 2. 汇总需要清除的所有 /32 单点路由
    host_targets: set[str] = set(st.get("injected_routes") or [])
    for cands in BNET_DEFAULT_CANDIDATES.values():
        for ip in cands:
            host_targets.add(ip)
    host_targets.add("59.111.19.33")

    # 检查当前系统路由表中有哪些目标实际存在
    rt_before = get_active_route_table_text()
    present_cidrs = []
    for (net, mask), cidr in sorted(cidr_targets.items()):
        if re.search(rf"^\s*{re.escape(net)}\s+{re.escape(mask)}\s+", rt_before, re.MULTILINE):
            present_cidrs.append((net, mask, cidr))

    present_hosts = []
    for ip in sorted(host_targets):
        if re.search(rf"^\s*{re.escape(ip)}\s+255\.255\.255\.255\s+", rt_before, re.MULTILINE):
            present_hosts.append(ip)

    delete_cmds: list[list[str]] = []
    for (net, mask), _cidr in sorted(cidr_targets.items(), key=lambda x: x[0]):
        delete_cmds.append(["route", "delete", net, "mask", mask])
    for ip in sorted(host_targets):
        delete_cmds.append(["route", "delete", ip])

    if ((present_cidrs or present_hosts) and allow_elevate) or is_admin():
        run_elevated_route_commands(delete_cmds, op_title="一键还原并清除战网无线分流网段路由", script_name="Restore_BattleNet_WLAN_Routes.bat")

    # 校验清除后路由表状态
    rt_after = get_active_route_table_text()
    remaining_cidrs = 0
    for net, mask, _cidr in present_cidrs:
        if re.search(rf"^\s*{re.escape(net)}\s+{re.escape(mask)}\s+", rt_after, re.MULTILINE):
            remaining_cidrs += 1
    deleted_cidr_count = max(0, len(present_cidrs) - remaining_cidrs)

    remaining_hosts = 0
    for ip in present_hosts:
        if re.search(rf"^\s*{re.escape(ip)}\s+255\.255\.255\.255\s+", rt_after, re.MULTILINE):
            remaining_hosts += 1
    deleted_host_count = max(0, len(present_hosts) - remaining_hosts)

    if verbose and present_cidrs:
        for net, mask, cidr in present_cidrs:
            still = bool(re.search(rf"^\s*{re.escape(net)}\s+{re.escape(mask)}\s+", rt_after, re.MULTILINE))
            print(f"    - 还原网段路由 {cidr:<18} (mask {mask:<15}) -> {'已彻底移除' if not still else '仍存在(需管理员权限)'}")

    hosts_cleaned = False
    if os.path.exists(HOSTS_PATH):
        try:
            raw = open(HOSTS_PATH, encoding="utf-8", errors="replace").read()
            pattern = re.compile(re.escape(HOSTS_START) + r".*?" + re.escape(HOSTS_END) + r"\r?\n?", re.DOTALL)
            new_raw, n = pattern.subn("", raw)
            if n > 0:
                with open(HOSTS_PATH, "w", encoding="utf-8") as f:
                    f.write(new_raw)
                hosts_cleaned = True
        except PermissionError:
            pass
    return deleted_cidr_count, deleted_host_count, hosts_cleaned


def cmd_enable(start_guard: bool = True) -> int:
    print("=" * 78)
    print("  [开启] 暴雪战网 / 炉石传说 / 守望先锋 无线网卡 (WLAN) 网段路由分流加速 v1.4")
    print("=" * 78)

    net_info = detect_network_interfaces()
    wlan = net_info.get("wlan") or {}
    pppoe = net_info.get("pppoe") or {}
    if not wlan.get("ok"):
        print(f"[!] 未检测到已连接的无线网卡 (WLAN): {wlan}")
        return 1

    wlan_ip = wlan["ip"]
    wlan_gw = wlan["gw"]
    wlan_if = wlan["ifIndex"]
    print(f"[*] 无线校园网接口 : {wlan['alias']} (IF={wlan_if}, IP={wlan_ip}, 网关={wlan_gw})")
    if pppoe.get("ok"):
        print(f"[*] 有线校园网接口 : {pppoe['alias']} (IF={pppoe['ifIndex']}, IP={pppoe['ip']}) [保持默认路由 0.0.0.0/0 不变]")

    # 确保关闭全局 TUN 劫持，彻底保护有线 PPPoE 与信大锐捷心跳
    ensure_tun_disabled_safe()
    clean_previous_injection(verbose=False, allow_elevate=False)

    # 1. 优选战网登录/更新/版本域名无线节点
    print("[*] 正在通过无线网卡 (WLAN) 并发探测暴雪战网与网易雷火最优节点...")
    chosen_real_ips = {}
    all_route_ips = set()

    def _probe_domain(dom: str):
        cands = []
        for ip in dns_query_via_wlan(dom, wlan_ip, "223.5.5.5"):
            if ip not in cands:
                cands.append(ip)
        for ip in BNET_DEFAULT_CANDIDATES.get(dom, []):
            if ip not in cands:
                cands.append(ip)
        if "actual.battlenet" in dom or "patch.battlenet" in dom:
            port = 1119
        elif "version.battlenet" in dom:
            port = 443
        else:
            port = 80
        best_ip = None
        best_ms = 99999.0
        local_ips = []
        for ip in cands[:4]:
            local_ips.append(ip)
            ms = probe_bnet_node(ip, dom, wlan_ip=wlan_ip, port=port)
            if 0 < ms < best_ms:
                best_ms = ms
                best_ip = ip
        if not best_ip and cands:
            best_ip = cands[0]
        return dom, port, best_ip, best_ms, local_ips

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        dom_results = list(ex.map(_probe_domain, BNET_DOMAINS))

    for dom, port, best_ip, best_ms, local_ips in dom_results:
        for ip in local_ips:
            all_route_ips.add(ip)
        if best_ip:
            chosen_real_ips[dom] = {"real_ip": best_ip, "latency_ms": best_ms if best_ms < 9999 else -1}
            print(f"    + {dom:<38} -> 优选无线节点 {best_ip:<15} (WLAN 实测 :{port} = {best_ms:.1f} ms)")

    tact_ip = chosen_real_ips.get("blzdist-phx.necdn.leihuo.netease.com", {}).get("real_ip", "113.137.43.176")
    aurora_ip = chosen_real_ips.get("cn.actual.battlenet.com.cn", {}).get("real_ip", "118.31.18.157")
    patch_ip = chosen_real_ips.get("cn.version.battlenet.com.cn", {}).get("real_ip", "8.149.233.11")

    ok_tunnels = ensure_mihomo_bnet_tunnels(tact_ip, aurora_ip, patch_ip)
    ok_group = set_mihomo_bnet_group(WLAN_PROXY_NAME)
    print(f"[*] Clash Verge 本地无线透明隧道 (127.0.0.11~13) 同步: {'成功' if ok_tunnels else '跳过'}")
    print(f"[*] Clash Verge 策略组「{BNET_GROUP_NAME}」->「{WLAN_PROXY_NAME}」: {'成功' if ok_group else '未运行或失败'}")

    # 2. 构建并批量注入战网/炉石/守望先锋对局集群 CIDR 网段路由 + 单点主机路由
    cidr_plan, discovered_game_servers = build_full_cidr_plan()
    if discovered_game_servers:
        gs_str = ", ".join(f"{ip}:{pt}" for ip, pt in discovered_game_servers[:6])
        print(f"[*] 从炉石传说日志 (GameNetLogger.log) 识别到历史对局服务器: {gs_str}")

    route_cmds: list[list[str]] = []
    for net, mask, _cidr, _desc in cidr_plan:
        route_cmds.append(["route", "delete", net, "mask", mask])
        route_cmds.append(["route", "add", net, "mask", mask, wlan_gw, "metric", "5", "if", str(wlan_if)])

    for ip in sorted(all_route_ips):
        route_cmds.append(["route", "delete", ip])
        route_cmds.append(["route", "add", ip, "mask", "255.255.255.255", wlan_gw, "metric", "5", "if", str(wlan_if)])

    run_elevated_route_commands(route_cmds, op_title="注入战网与炉石对局集群无线网卡 CIDR 网段路由", script_name="Apply_BattleNet_WLAN_Routes.bat")

    # 校验 CIDR 网段路由注入结果
    cidr_verify = verify_cidr_routes_in_os_table(cidr_plan, wlan_gw=wlan_gw)
    injected_cidr_routes = [item for item in cidr_verify if item["present"]]
    rt_now = get_active_route_table_text()
    injected_host_routes = [
        ip for ip in sorted(all_route_ips)
        if re.search(rf"^\s*{re.escape(ip)}\s+255\.255\.255\.255\s+", rt_now, re.MULTILINE)
    ]

    print(f"[*] 战网/炉石对局集群 CIDR 网段路由注入结果: {len(injected_cidr_routes)}/{len(cidr_plan)} 条已写入内核路由表 (GW={wlan_gw}, IF={wlan_if}, Metric=5)")
    for item in injected_cidr_routes:
        print(f"    [OK] {item['cidr']:<18} (mask {item['mask']:<15}) -> {wlan_gw} [IF={wlan_if}] | {item['desc']}")

    # 3. 更新系统 Hosts：若静态路由已生效，直接映射到真实 IP 走内核无线路由（支持原生 TLS SNI）；否则回退到 127.0.0.11~13 无线隧道
    routes_effective = len(injected_cidr_routes) >= 8
    use_loopback_tunnel = (not routes_effective) and ok_tunnels and ok_group
    chosen_hosts = {}
    hosts_lines = [
        HOSTS_START,
        f"# Updated at {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} via WLAN ({wlan_ip}) [mode={'wlan_cidr_route' if routes_effective else 'mihomo_wlan_tunnel'}]",
    ]
    for dom, info in chosen_real_ips.items():
        # cn.version.battlenet.com.cn 在路由生效时直接写 real_ip (8.149.233.11 / 47.114.126.40)，彻底避免任何 TLS 证书不匹配
        mapped_ip = BNET_TUNNEL_LOOPBACK.get(dom, info["real_ip"]) if use_loopback_tunnel else info["real_ip"]
        chosen_hosts[dom] = {
            "ip": mapped_ip,
            "real_ip": info["real_ip"],
            "latency_ms": info["latency_ms"],
            "via": "wlan_cidr_route" if routes_effective else "mihomo_wlan_tunnel",
        }
        hosts_lines.append(f"{mapped_ip:<16} {dom} # WLAN->{info['real_ip']} ({info['latency_ms']}ms)")
    hosts_lines.append(HOSTS_END)
    block_text = "\n".join(hosts_lines) + "\n"

    try:
        raw_hosts = open(HOSTS_PATH, encoding="utf-8", errors="replace").read()
        if not raw_hosts.endswith("\n"):
            raw_hosts += "\n"
        with open(HOSTS_PATH, "w", encoding="utf-8") as f:
            f.write(raw_hosts + block_text)
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True)
        print(f"[*] 已更新系统 Hosts 战网锚点块并刷新 DNS 缓存 (模式: {'无线 CIDR 路由直连' if routes_effective else 'Clash 无线透明隧道'})")
    except PermissionError:
        print(f"[!] 写入系统 Hosts 需要管理员权限（请通过 Start_BattleNet_WLAN_Switch.bat 启动）")

    # 4. 若已是管理员权限且开启了后台对局动态路由守护，拉起静默守护进程
    watch_pid = None
    if start_guard and is_admin() and os.path.isdir(HEARTHSTONE_LOG_DIR):
        try:
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            proc = subprocess.Popen(
                [sys.executable, "-X", "utf8", os.path.abspath(__file__), "--watch-matchmaking-daemon"],
                cwd=HERE,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            watch_pid = proc.pid
            print(f"[*] 已启动后台【炉石/守望对局 IP 动态路由守护进程】(PID={watch_pid})，新对局网段将自动分流至无线网卡")
        except Exception:
            pass

    save_state({
        "version": "1.4",
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "enabled",
        "clash_group_selected": WLAN_PROXY_NAME,
        "tun_enabled": False,
        "wlan_interface": wlan,
        "pppoe_interface": pppoe,
        "injected_cidr_routes": injected_cidr_routes,
        "injected_routes": injected_host_routes,
        "discovered_game_servers": [{"ip": ip, "port": pt} for ip, pt in discovered_game_servers],
        "hosts_mapping": chosen_hosts,
        "watch_pid": watch_pid,
    })

    if not routes_effective:
        print("[!] 警告：当前 CIDR 网段静态路由尚未写入系统内核路由表（需要管理员权限允许 UAC 提权）。")
        print("    请双击运行 Start_BattleNet_WLAN_Switch.bat 选择 [1] 完成管理员权限网段路由注入。")
        return 2

    print("[✓] 暴雪战网、炉石传说与守望先锋无线网段分流已全面生效（有线拨号保持默认不受影响）！")
    return 0


def cmd_disable() -> int:
    print("=" * 78)
    print("  [一键还原] 正在清除全部已注入的战网 CIDR 网段路由、单点路由与 Hosts 规则...")
    print("=" * 78)
    deleted_cidrs, deleted_hosts, hosts_cleaned = clean_previous_injection(verbose=True)
    ok_group = set_mihomo_bnet_group(WIRED_DIRECT_PROXY_NAME)
    ensure_tun_disabled_safe()
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True)

    # 校验是否还有残留的 CIDR 网段路由
    cidr_plan, _ = build_full_cidr_plan()
    verify_after = verify_cidr_routes_in_os_table(cidr_plan)
    still_present = [x for x in verify_after if x["present"]]

    save_state({
        "version": "1.4",
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "disabled",
        "clash_group_selected": WIRED_DIRECT_PROXY_NAME,
        "tun_enabled": False,
        "injected_cidr_routes": [],
        "injected_routes": [],
        "hosts_mapping": {},
        "watch_pid": None,
    })
    print(f"[*] 已清除战网/雷火/阿里云对局集群 CIDR 网段路由: {deleted_cidrs} 条 (当前残留: {len(still_present)} 条)")
    print(f"[*] 已清除战网域名 /32 单点主机路由            : {deleted_hosts} 条")
    print(f"[*] 系统 Hosts 战网分流锚点块清理              : {'已彻底清除' if hosts_cleaned else '无残留'}")
    print(f"[*] Clash 策略组「{BNET_GROUP_NAME}」恢复默认 : {'成功' if ok_group else '跳过'}")
    print("[✓] 已一键完整还原至纯有线默认网络状态！")
    return 0


def watch_matchmaking_loop(foreground: bool = True, duration_sec: int = 0) -> int:
    """
    实时监控 G:\\Hearthstone\\Logs\\*\\GameNetLogger.log 中的 GotoGameServe() 对局分配 IP：
    一旦发现任何尚未被当前路由表覆盖的对局 IP，立即动态注入其 /24 无线网段路由并记录到状态文件（支持一键还原）。
    """
    wlan = detect_wlan_interface()
    if not wlan.get("ok"):
        if foreground:
            print("[!] 未检测到已连接的无线网卡 (WLAN)，无法启动对局路由守护。")
        return 1

    wlan_gw = wlan["gw"]
    wlan_if = wlan["ifIndex"]
    cidr_plan, _ = build_full_cidr_plan()
    known_cidrs = list(cidr_plan)

    if foreground:
        print("=" * 78)
        print(f"  [守护] 炉石传说 / 守望先锋 匹配对局 IP 实时动态路由守护已启动")
        print(f"  监控目录: {HEARTHSTONE_LOG_DIR} | 无线接口: {wlan['alias']} (IF={wlan_if}, GW={wlan_gw})")
        print("  说明: 当匹配对局分配到新网段 IP 时将自动注入 /24 无线路由，按 Ctrl+C 可随时退出。")
        print("=" * 78)

    t_start = time.time()
    seen_ips: set[str] = set()
    try:
        while True:
            discovered = discover_game_server_ips_from_logs()
            for ip_str, port in discovered:
                if ip_str in seen_ips or ip_str.startswith(("127.", "10.", "192.168.")):
                    continue
                seen_ips.add(ip_str)
                cov = is_ip_covered_by_cidrs(ip_str, known_cidrs)
                if cov:
                    if foreground:
                        print(f"  [已覆盖] 对局服 {ip_str}:{port} 已命中网段路由 {cov} -> WLAN ({wlan_gw})")
                else:
                    parts = ip_str.split(".")
                    if len(parts) == 4:
                        net = f"{parts[0]}.{parts[1]}.{parts[2]}.0"
                        mask = "255.255.255.0"
                        cidr = f"{net}/24"
                        desc = f"实时守护动态追加对局网段 (源自 {ip_str}:{port})"
                        run_elevated_route_commands([
                            ["route", "delete", net, "mask", mask],
                            ["route", "add", net, "mask", mask, wlan_gw, "metric", "5", "if", str(wlan_if)],
                        ])
                        known_cidrs.append((net, mask, cidr, desc))
                        st = load_state()
                        cur_list = st.get("injected_cidr_routes") or []
                        cur_list.append({
                            "net": net,
                            "mask": mask,
                            "cidr": cidr,
                            "desc": desc,
                            "present": True,
                            "gateway": wlan_gw,
                            "interface": wlan["ip"],
                            "metric": 5,
                        })
                        st["injected_cidr_routes"] = cur_list
                        save_state(st)
                        if foreground:
                            print(f"  [动态注入] 发现新对局服 {ip_str}:{port}，已自动注入 {cidr} -> WLAN ({wlan_gw})！")

            if duration_sec > 0 and (time.time() - t_start) >= duration_sec:
                break
            time.sleep(2.0)
    except KeyboardInterrupt:
        if foreground:
            print("\n[*] 已退回主菜单。")
    return 0


def _probe_endpoint_default_route(target_host: str, port: int, desc: str, is_tls: bool = False, is_http: bool = False) -> dict:
    """不绑定本地网卡，直接使用系统默认 socket 测试进程真实出站网卡与连通性"""
    t0 = time.perf_counter()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.2)
    try:
        ip = socket.gethostbyname(target_host)
        s.connect((ip, port))
        local_ip = s.getsockname()[0]
        if is_tls:
            ctx = ssl.create_default_context()
            ss = ctx.wrap_socket(s, server_hostname=target_host)
            cert = ss.getpeercert()
            subj = dict(x[0] for x in cert.get("subject", []))
            detail = f"TLS OK (CN={subj.get('commonName')})"
            ss.close()
        elif is_http:
            req = (
                f"GET /tpr/catalogs/data/b2/81/b28162fb26a1983f3d33b4fe8ef0b829 HTTP/1.1\r\n"
                f"Host: {target_host}\r\nUser-Agent: Battle.net/2.53.8.17986\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            s.sendall(req)
            detail = s.recv(128).decode("latin1", errors="replace").splitlines()[0]
            s.close()
        else:
            detail = f"TCP:{port} Handshake OK"
            s.close()
        ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {"ok": True, "desc": desc, "host": target_host, "ip": ip, "port": port, "local_ip": local_ip, "ms": ms, "detail": detail}
    except Exception as e:
        try:
            s.close()
        except Exception:
            pass
        return {"ok": False, "desc": desc, "host": target_host, "ip": target_host, "port": port, "local_ip": "N/A", "ms": -1.0, "detail": f"{type(e).__name__}: {e}"}


def cmd_status() -> int:
    print("=" * 78)
    print("  [诊断] 暴雪战网 / 炉石传说 / 守望先锋 无线网段路由分流状态与对局服全链路实测")
    print("=" * 78)
    st = load_state()
    m_st = get_mihomo_status()
    net_info = detect_network_interfaces()
    wlan = net_info.get("wlan") or {}
    pppoe = net_info.get("pppoe") or {}
    elev = m_st.get("elevation") or {}

    cidr_plan, discovered = build_full_cidr_plan()
    cidr_verify = verify_cidr_routes_in_os_table(cidr_plan, wlan_gw=wlan.get("gw"))
    active_cidrs = [x for x in cidr_verify if x["present"]]

    default_if = net_info.get("defaultIfIndex")
    if pppoe.get("ok") and default_if == pppoe.get("ifIndex"):
        def_desc = f"有线宽带 {pppoe.get('alias')} (IP={pppoe.get('ip')}, IF={default_if}) [正常：有线不断联]"
    else:
        def_desc = f"IF={default_if} (有线PPPoE在线={pppoe.get('ok')}, IP={pppoe.get('ip')})"

    print(f"1. 控制器状态     : {st.get('status', 'unknown')} (版本: v1.4, 上次更新: {st.get('updated_at', 'N/A')})")
    print(f"2. 系统默认路由   : {def_desc}")
    print(f"3. 无线网卡状态   : {wlan.get('alias')} IP={wlan.get('ip')} 网关={wlan.get('gw')} (IF={wlan.get('ifIndex')})")
    print(f"4. Clash Verge状态: 内核在线={m_st['running']} (PID={elev.get('pid')}) | 策略组=「{m_st.get('group_now')}」 | 全局TUN={m_st.get('tun_enable')} (保持关闭防断联)")
    print(f"5. 内核生效网段数 : {len(active_cidrs)}/{len(cidr_plan)} 条战网/雷火/阿里云对局 CIDR 网段路由已生效 | Hosts 域名: {len(st.get('hosts_mapping') or {})} 个")
    print("-" * 78)
    print("6. 真实协议栈并发实测（不绑定网卡，直接检验游戏进程默认连接登录服 :1119 与炉石对局服 :3724 的实际出站路径）：")

    tasks = [
        ("blzdist-phx.necdn.leihuo.netease.com", 80, "战网 TACT 主更新 CDN (:80)", False, True),
        ("cn.version.battlenet.com.cn", 443, "战网版本校验 HTTPS (:443 TLS)", True, False),
        ("cn.actual.battlenet.com.cn", 1119, "国服战网 Aurora 登录网关 (:1119)", False, False),
    ]
    # 加入炉石传说 GameNetLogger.log 中的 4 个真实对局服务器 :3724
    seen_gs = set()
    for ip, pt in discovered:
        if pt == 3724 and ip not in seen_gs:
            seen_gs.add(ip)
            tasks.append((ip, pt, f"炉石传说实时匹配对局服 ({ip}:3724)", False, False))
    for ip, pt, desc in DEFAULT_MATCHMAKING_TEST_SERVERS:
        if ip not in seen_gs:
            seen_gs.add(ip)
            tasks.append((ip, pt, desc, False, False))

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(_probe_endpoint_default_route, h, p, d, tls, http) for (h, p, d, tls, http) in tasks]
        results = [f.result() for f in futs]

    for r in results:
        lip = r["local_ip"]
        if lip.startswith("10.175."):
            via = f"WLAN 无线网段路由直连 ({lip})"
        elif str(r["ip"]).startswith("127.0.0."):
            via = f"Clash 无线隧道 ({r['ip']} -> WLAN {wlan.get('ip')})"
        elif lip.startswith("10.192."):
            via = f"有线 PPPoE ({lip}) [未分流!]"
        else:
            via = f"接口 ({lip})"

        if r["ok"]:
            print(f"  [PASS] {r['desc']:<36} | 目标={r['ip']}:{r['port']:<4} | 出站={via} | {r['ms']:>5.1f}ms | {r['detail']}")
        else:
            print(f"  [FAIL] {r['desc']:<36} | 目标={r['ip']}:{r['port']:<4} | 出站={via} | 错误={r['detail']}")
    return 0


def interactive_menu() -> int:
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("西电校园网 暴雪战网 / 炉石传说 / 守望先锋 无线网段路由分流控制器 v1.4")
    except Exception:
        pass
    while True:
        print()
        cmd_status()
        print("=" * 78)
        print("  西电校园网 暴雪战网 / 炉石传说 / 守望先锋 无线网段分流控制台 v1.4")
        print("=" * 78)
        print("    [1] 一键开启【战网 + 炉石传说 + 守望先锋 无线 CIDR 网段路由分流加速】")
        print("        (注入阿里云杭州/网易雷火对局集群 16 个 CIDR 网段路由 + Hosts 防劫持，绝不干扰有线拨号)")
        print("    [2] 一键还原【彻底清除全部已注入的战网 CIDR 网段路由、单点路由与 Hosts 映射】")
        print("        (恢复纯有线默认路由表与 Clash 默认策略组，零残留还原)")
        print("    [3] 状态诊断【重新核验系统路由表并实测战网登录(:1119)与炉石对局服(:3724)连通性】")
        print("    [4] 动态守护【前台启动炉石/守望匹配对局 IP 实时日志监控，新网段自动注入无线路由】")
        print("    [0] 退出")
        print("=" * 78)
        try:
            choice = input("请输入选项编号 [0-4]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if choice == "1":
            print()
            cmd_enable(start_guard=True)
            try:
                input("\n按回车键返回主菜单并刷新状态...")
            except (EOFError, KeyboardInterrupt):
                return 0
        elif choice == "2":
            print()
            cmd_disable()
            try:
                input("\n按回车键返回主菜单并刷新状态...")
            except (EOFError, KeyboardInterrupt):
                return 0
        elif choice == "3":
            continue
        elif choice == "4":
            print()
            watch_matchmaking_loop(foreground=True)
        elif choice == "0" or choice == "":
            return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="暴雪战网 / 炉石传说 / 守望先锋 无线网卡网段路由分流控制器 v1.4")
    ap.add_argument("--enable", "--enable-wlan", dest="enable", action="store_true", help="一键开启战网与炉石/守望对局集群无线 CIDR 网段路由分流")
    ap.add_argument("--disable", "--disable-wlan", "--clean", "--restore", dest="disable", action="store_true", help="一键还原：彻底清除全部已注入的 CIDR 网段路由、单点路由与 Hosts 规则")
    ap.add_argument("--status", action="store_true", help="查看当前生效的网段路由并实测登录服(:1119)与炉石对局服(:3724)连通性")
    ap.add_argument("--watch-matchmaking", action="store_true", help="前台运行炉石/守望对局日志实时动态路由守护")
    ap.add_argument("--watch-matchmaking-daemon", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-guard", action="store_true", help="开启分流时不启动后台对局动态路由守护进程")
    args = ap.parse_args()

    if args.watch_matchmaking_daemon:
        return watch_matchmaking_loop(foreground=False, duration_sec=14400)
    if args.watch_matchmaking:
        return watch_matchmaking_loop(foreground=True)
    if args.enable:
        return cmd_enable(start_guard=not args.no_guard)
    if args.disable:
        return cmd_disable()
    if args.status:
        return cmd_status()
    return interactive_menu()


if __name__ == "__main__":
    sys.exit(main())
