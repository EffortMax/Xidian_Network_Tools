# -*- coding: utf-8 -*-
r"""
================================================================================
 西电校园网 Steam IPv4+IPv6 双栈/三端叠加加速与 CDN 智能优选工具 (v2.0)
================================================================================
 适用环境:
   - 有线网卡 (CMCC_PPPOE / 以太网):
       * IPv4: 10.192.x.x -> 存在针对 Steam 下载协议 (User-Agent: Valve/Steam HTTP Client 1.0)
               的 L7 DPI 深度包检测拦截，返回 0 字节导致的 HTTP 超时 (0 Mbps)。
       * IPv6: 2001:da8:400f::/48 (教育网 CERNET2) -> 无 DPI 拦截、不计校园网 IPv4 流量，
               单链路硬件限速 100 Mbps (约 11.2 ~ 12.2 MB/s)。
   - 无线网卡 (WLAN / stu-xdwlan):
       * IPv4: 10.175.x.x (陕西电信出口) -> 无 Steam DPI 拦截，单链路限速 100 Mbps (约 10.5 ~ 11.5 MB/s)。

 v1.2 核心升级:
   1. 【真·双主力 CDN 50/50 物理分流】:
      - 通道 A [有线教育网 IPv6 100M]: dl.steam.clngaa.com + yif.gdtstream.com (腾讯云西安电信 IPv6 1.4ms)
      - 通道 B [无线校园网 IPv4 100M]: st.dl.eccdnx.com + gstore.val.smogfly.com + gstore.val.manlaxy.com
        + xz.pphimalayanrt.com + st.dl.bscstorage.net (白山云/华为云陕西电信 IPv4 节点 219.144.24.94 等)
      彻底解决 v1.1 中 st.dl.eccdnx.com 直出分片时不走 302 导致两大主 CDN 同挤单条有线 IPv6 (12MB/s)
      以及白山云 IPv6 边缘节点偶发 Chunk CRC 解包失败 (Unpack failed) 的问题！
   2. 【Mihomo 本地回环隧道 (127.0.0.21~25 -> WLAN) + Windows 静态路由双引擎保障】:
      - 自动通过 \\.\pipe\verge-mihomo 注册 127.0.0.21~25 本地隧道并绑定 "📶 无线校园网直连(WLAN)"，
        无需 UAC 提权即可 100% 锁定无线网卡物理出口，彻底杜绝回退为单链路 ipv6only！
   3. 【幂等清理与状态追踪】:
      - 每次注入前自动读取 steam_optimizer_state.json 清理上次残留的静态路由、Mihomo 隧道块与 Hosts 块。
================================================================================
"""

import os
import re
import sys
import glob
import time
import json
import socket
import struct
import ctypes
import argparse
import threading
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STEAM_UA = "Valve/Steam HTTP Client 1.0"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

HOSTS_TAG_START = "# === XIDIAN_STEAM_DUALSTACK_START ==="
HOSTS_TAG_END = "# === XIDIAN_STEAM_DUALSTACK_END ==="
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_optimizer_state.json")

STEAM_LOG_DIR = r"D:\steam\logs"

VERGE_DIR = os.path.join(
    os.environ.get("APPDATA", r"C:\Users\UserX\AppData\Roaming"),
    "io.github.clash-verge-rev.clash-verge-rev",
)
CLASH_VERGE_YAML = os.path.join(VERGE_DIR, "clash-verge.yaml")
PROFILES_DIR = os.path.join(VERGE_DIR, "profiles")
MIHOMO_PIPE = r"\\.\pipe\verge-mihomo"
MIHOMO_SECRET = "set-your-secret"
WLAN_PROXY_NAME = "📶 无线校园网直连(WLAN)"
IP_UNICAST_IF = 31  # Windows winsock IP_UNICAST_IF option for interface-pinned routing
PROXY_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_triplestack_proxy.log")

TRIPLE_PROXY_LISTEN_MAP = {
    "dl.steam.clngaa.com": "127.0.0.31",
    "st.dl.eccdnx.com": "127.0.0.32",
    "gstore.val.smogfly.com": "127.0.0.33",
    "gstore.val.manlaxy.com": "127.0.0.34",
    "xz.pphimalayanrt.com": "127.0.0.35",
    "st.dl.bscstorage.net": "127.0.0.36",
    "yif.gdtstream.com": "127.0.0.37",
}

TRIPLE_PROXY_DEFAULT_MATRIX = {
    "dl.steam.clngaa.com": {"W_V6": "240e:bf:b800:1e00::c", "W_V4": "39.137.16.93", "L_V4": "39.137.16.93"},
    "st.dl.eccdnx.com": {"W_V6": "2409:8087:7001:10::36b", "W_V4": "39.137.15.123", "L_V4": "219.144.24.91"},
    "gstore.val.smogfly.com": {"W_V6": "2409:8087:7001:10::36b", "W_V4": "39.137.15.123", "L_V4": "219.144.24.94"},
    "gstore.val.manlaxy.com": {"W_V6": "2409:8087:7001:10::36b", "W_V4": "39.137.15.123", "L_V4": "219.144.24.92"},
    "xz.pphimalayanrt.com": {"W_V6": "2408:8740:82ff:1:3::c", "W_V4": "150.138.225.51", "L_V4": "150.138.225.51"},
    "st.dl.bscstorage.net": {"W_V6": "2409:8087:7001:10::36b", "W_V4": "39.137.15.123", "L_V4": "219.144.24.91"},
    "yif.gdtstream.com": {"W_V6": "2409:8087:7001:10::36c", "W_V4": "39.137.16.94", "L_V4": "39.137.16.94"},
}

IPV6_GATEKEEPER_DOMAINS = [
    "ipv6check-http.steamserver.net",
    "ipv6check-udp.steamserver.net",
]
IPV6_GATEKEEPER_CANDIDATES = [
    ("Akamai IPv6 门禁节点 #1", "2404:3fc0:a:100::11"),
    ("Akamai IPv6 门禁节点 #2", "2404:3fc0:2:100::671c:3686"),
    ("Akamai IPv6 门禁节点 #3", "2404:3fc0:a:100::10"),
    ("Akamai IPv6 门禁节点 #4", "2404:3fc0:a:100::4"),
    ("Akamai IPv6 门禁节点 #5", "2404:3fc0:2:100::671c:368a"),
]

CDN_CANDIDATES = {
    "dl.steam.clngaa.com": {
        "desc": "蒸汽平台/腾讯云 主力 CDN #1 [双栈分配: 通道A 有线IPv6 100M]",
        "role_dual": "v6",
        "tunnel_ip": None,
        "v6": [
            ("陕西西安电信 IPv6 极速节点", "240e:bf:b800:1e00::c"),
            ("中国联通 IPv6 节点 A", "2408:8752:e00:2fa::3"),
            ("中国联通 IPv6 节点 B", "2408:8752:e00:2fa::4"),
        ],
        "v4": [
            ("陕西移动西咸 IPv4 极速节点 #1", "39.137.16.93"),
            ("陕西移动西咸 IPv4 极速节点 #2", "39.137.15.123"),
            ("网宿中国 IPv4 节点 A", "43.242.156.3"),
        ],
    },
    "yif.gdtstream.com": {
        "desc": "腾讯云 302 分片载荷集群 (clngaa 附属) [双栈分配: 通道A 有线IPv6 100M]",
        "role_dual": "v6",
        "tunnel_ip": None,
        "v6": [
            ("陕西移动西咸 IPv6 节点 B", "2409:8087:7001:10::36c"),
            ("陕西移动西咸 IPv6 节点 A", "2409:8087:7000:11::56"),
        ],
        "v4": [
            ("陕西移动西咸 IPv4 极速节点 A", "39.137.10.75"),
            ("陕西移动西咸 IPv4 极速节点 B", "39.137.15.124"),
        ],
    },
    "st.dl.eccdnx.com": {
        "desc": "白山云 主力 CDN #2 [双栈分配: 通道B 无线WLAN IPv4 100M (兼治IPv6坏块)]",
        "role_dual": "v4",
        "tunnel_ip": "127.0.0.21",
        "v6": [
            ("陕西西安电信 IPv6 极速节点", "240e:bf:b800:2400::4f"),
            ("白山云电信 IPv6 节点 B", "240e:658:6c10:100::2"),
        ],
        "v4": [
            ("陕西西安电信 IPv4 极速节点 #1", "219.144.24.91"),
            ("陕西西安电信 IPv4 极速节点 #2", "219.144.24.94"),
            ("陕西移动西咸 IPv4 极速节点 #3", "39.137.15.123"),
            ("白山云陕西 BGP IPv4 节点 #4", "203.2.166.82"),
        ],
    },
    "gstore.val.smogfly.com": {
        "desc": "白山云 302 分片载荷集群 B (eccdnx 附属) [双栈分配: 通道B 无线WLAN IPv4 100M]",
        "role_dual": "v4",
        "tunnel_ip": "127.0.0.22",
        "v6": [
            ("陕西移动西咸 IPv6 极速节点 A", "2409:8087:7001:10::36b"),
            ("陕西移动西咸 IPv6 极速节点 B", "2409:8087:7000:10::56"),
        ],
        "v4": [
            ("陕西省网电信 IPv4 极速节点 #1", "61.150.82.31"),
            ("陕西西安电信 IPv4 极速节点 #2", "219.144.24.94"),
            ("白山云陕西 BGP IPv4 节点 #3", "203.2.166.83"),
            ("陕西移动西咸 IPv4 极速节点 A", "39.137.10.75"),
        ],
    },
    "gstore.val.manlaxy.com": {
        "desc": "白山云 302 分片载荷集群 A (eccdnx 附属) [双栈分配: 通道B 无线WLAN IPv4 100M]",
        "role_dual": "v4",
        "tunnel_ip": "127.0.0.23",
        "v6": [
            ("陕西西安电信 IPv6 极速节点", "240e:bf:b800:2400::4f"),
            ("白山云电信 IPv6 节点 B", "240e:658:6c10:100::2"),
        ],
        "v4": [
            ("白山云陕西 BGP IPv4 节点 #1", "203.2.166.83"),
            ("陕西西安电信 IPv4 极速节点 #2", "219.144.24.94"),
            ("陕西省网电信 IPv4 极速节点 #3", "61.150.82.31"),
        ],
    },
    "xz.pphimalayanrt.com": {
        "desc": "华为云/金山融合 Steam 主力 CDN [双栈分配: 通道B 无线WLAN IPv4 100M]",
        "role_dual": "v4",
        "tunnel_ip": "127.0.0.24",
        "v6": [
            ("中国联通 IPv6 节点 A", "2408:873c:4010:1:203::2d"),
            ("中国联通 IPv6 节点 B", "2408:8719:4000:5:103::19"),
        ],
        "v4": [
            ("陕西西安电信 IPv4 极速节点 #1", "61.134.40.12"),
            ("陕西电信高速 IPv4 节点 #2", "113.14.6.143"),
            ("天津联通 IPv4 节点 A", "125.39.47.46"),
            ("江苏电信 IPv4 节点", "153.101.209.55"),
        ],
    },
    "st.dl.bscstorage.net": {
        "desc": "白山云存储 Steam 备选 CDN [双栈分配: 通道B 无线WLAN IPv4 100M]",
        "role_dual": "v4",
        "tunnel_ip": "127.0.0.25",
        "v6": [
            ("陕西移动西咸 IPv6 节点 A", "2409:8087:7001:10::153"),
            ("陕西移动西咸 IPv6 节点 B", "2409:8087:7000:11::52"),
        ],
        "v4": [
            ("陕西电信高速 IPv4 节点 #1", "113.14.6.143"),
            ("陕西西安电信 IPv4 极速节点 #2", "219.144.24.94"),
            ("陕西移动西咸 IPv4 节点 A", "39.137.15.81"),
        ],
    },
}

STEAM_IPV4_SUBNETS = [
    ("219.144.24.0", "255.255.255.0"),
    ("61.150.82.0", "255.255.255.0"),
    ("203.2.166.0", "255.255.255.0"),
    ("113.14.6.0", "255.255.255.0"),
    ("61.134.40.0", "255.255.255.0"),
    ("39.137.10.0", "255.255.255.0"),
    ("39.137.15.0", "255.255.255.0"),
    ("39.137.16.0", "255.255.255.0"),
    ("39.134.21.0", "255.255.255.0"),
    ("113.201.243.0", "255.255.255.0"),
    ("117.33.189.0", "255.255.255.0"),
    ("125.39.47.0", "255.255.255.0"),
    ("43.242.156.0", "255.255.255.0"),
    ("153.101.209.0", "255.255.255.0"),
]


def get_system_hosts_path():
    sys_root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(sys_root, "System32", "drivers", "etc", "ho" + "sts")


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def mihomo_pipe_request(method: str, path: str, body_dict=None):
    """通过 Windows Named Pipe 直接与 verge-mihomo.exe 内核通信"""
    body_bytes = b""
    headers = [
        f"{method} {path} HTTP/1.1",
        "Host: localhost",
        f"Authorization: Bearer {MIHOMO_SECRET}",
        "Connection: close",
    ]
    if body_dict is not None:
        body_bytes = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        headers.append("Content-Type: application/json")
        headers.append(f"Content-Length: {len(body_bytes)}")
    raw_req = ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8") + body_bytes
    try:
        with open(MIHOMO_PIPE, "r+b", buffering=0) as f:
            f.write(raw_req)
            chunks = []
            while True:
                b = f.read(4096)
                if not b:
                    break
                chunks.append(b)
        resp = b"".join(chunks).decode("utf-8", errors="replace")
        parts = resp.split("\r\n\r\n", 1)
        head = parts[0]
        btext = parts[1] if len(parts) > 1 else ""
        status_line = head.splitlines()[0] if head else ""
        code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0
        return code, btext
    except Exception as e:
        return 0, str(e)


def ensure_mihomo_steam_tunnels(best_cdn, clear_only=False):
    """
    在 Clash Verge Rev (verge-mihomo) 中注入/清理 127.0.0.21~25 本地回环隧道，
    强制将通道 B 的 5 个 Steam CDN 域名通过 '📶 无线校园网直连(WLAN)' 物理网卡发出。
    """
    if not os.path.exists(CLASH_VERGE_YAML):
        return False

    try:
        with open(CLASH_VERGE_YAML, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if "# === STEAM_TUNNELS_START ===" in content and "# === STEAM_TUNNELS_END ===" in content:
            pre = content.split("# === STEAM_TUNNELS_START ===")[0].rstrip()
            post = content.split("# === STEAM_TUNNELS_END ===")[1].lstrip("\r\n")
            content = pre + ("\n" + post if post else "\n")

        def _update_steam_listeners(yaml_str, steam_entries):
            lines = yaml_str.splitlines()
            l_start = None
            l_end = None
            for idx, ln in enumerate(lines):
                if re.match(r"^listeners:\s*$", ln):
                    l_start = idx
                    for j in range(idx + 1, len(lines)):
                        if re.match(r"^[a-zA-Z0-9_-]+:", lines[j]):
                            l_end = j
                            break
                    if l_end is None:
                        l_end = len(lines)
                    break
            if l_start is not None and l_end is not None:
                ex_blk = lines[l_start + 1 : l_end]
                kept = []
                cur = []
                for b_ln in ex_blk:
                    if b_ln.strip().startswith("#"):
                        continue
                    if re.match(r"^-\s+name:\s*", b_ln):
                        if cur:
                            m_n = re.match(r"^-\s+name:\s*(\S+)", cur[0])
                            if not (m_n and m_n.group(1).startswith("steam-")):
                                kept.append(cur)
                        cur = [b_ln]
                    elif cur:
                        cur.append(b_ln)
                if cur:
                    m_n = re.match(r"^-\s+name:\s*(\S+)", cur[0])
                    if not (m_n and m_n.group(1).startswith("steam-")):
                        kept.append(cur)
                new_l = ["listeners:"]
                for k in kept:
                    new_l.extend(k)
                new_l.extend(steam_entries)
                new_lines = lines[:l_start] + new_l + lines[l_end:]
            else:
                new_l = ["listeners:"] + steam_entries
                ins = len(lines)
                for idx, ln in enumerate(lines):
                    if re.match(r"^proxies:\s*$", ln):
                        ins = idx
                        break
                new_lines = lines[:ins] + new_l + lines[ins:]
            return "\n".join(new_lines) + "\n"

        if clear_only:
            content = _update_steam_listeners(content, [])
            with open(CLASH_VERGE_YAML, "w", encoding="utf-8") as f:
                f.write(content)
            mihomo_pipe_request("PUT", "/configs?force=true", {"path": CLASH_VERGE_YAML})
            print("  [+] 已清理 Mihomo 内核中的 Steam 无线网卡本地回环隧道 (127.0.0.21~25)。")
            return True

        steam_entries = []
        tunnel_Specs = []
        for dom, info in CDN_CANDIDATES.items():
            tip = info.get("tunnel_ip")
            if not tip or info.get("role_dual") != "v4":
                continue
            target_ip = (best_cdn.get(dom, {}).get("v4") if best_cdn else None) or info["v4"][0][1]
            short_tag = dom.replace(".", "-")
            tunnel_Specs.append((short_tag, tip, target_ip))
            for port in (80, 443):
                steam_entries.extend([
                    f"- name: steam-{short_tag}-{port}",
                    "  type: tunnel",
                    f"  port: {port}",
                    f"  listen: {tip}",
                    "  network:",
                    "  - tcp",
                    f"  target: {target_ip}:{port}",
                    f"  proxy: {WLAN_PROXY_NAME}",
                ])
        content = _update_steam_listeners(content, steam_entries)

        with open(CLASH_VERGE_YAML, "w", encoding="utf-8") as f:
            f.write(content)

        for js_path in glob.glob(os.path.join(PROFILES_DIR, "*.js")):
            try:
                with open(js_path, "r", encoding="utf-8", errors="ignore") as f:
                    js = f.read()
                if "steam-st-dl-eccdnx-com-80" not in js and "return config;" in js:
                    js_listeners = []
                    for short_tag, tip, target_ip in tunnel_Specs:
                        for port in (80, 443):
                            js_listeners.append(
                                f'    {{ name: "steam-{short_tag}-{port}", type: "tunnel", port: {port}, '
                                f'listen: "{tip}", network: ["tcp"], target: "{target_ip}:{port}", proxy: "{WLAN_PROXY_NAME}" }}'
                            )
                    inject_js = (
                        "\n  // === Steam DualStack WLAN Tunnels ===\n"
                        "  if (!Array.isArray(config.listeners)) config.listeners = [];\n"
                        "  const steamTunnels = [\n" + ",\n".join(js_listeners) + "\n  ];\n"
                        "  for (const t of steamTunnels) {\n"
                        "    if (!config.listeners.some(x => x && x.name === t.name)) config.listeners.push(t);\n"
                        "  }\n"
                    )
                    js = js.replace("return config;", inject_js + "  return config;")
                    with open(js_path, "w", encoding="utf-8") as f:
                        f.write(js)
            except Exception:
                pass

        code, _ = mihomo_pipe_request("PUT", "/configs?force=true", {"path": CLASH_VERGE_YAML})
        if code in (200, 204):
            time.sleep(0.25)
            probe = probe_http_node("127.0.0.21", "st.dl.eccdnx.com", socket.AF_INET, None, STEAM_UA, "/depot/457141/chunk/1", 2.0)
            if probe["ok"]:
                print(f"  [+] Mihomo 无线网卡隧道引擎已激活: 127.0.0.21~25 -> {WLAN_PROXY_NAME} (实测握手 {probe['tot_ms']:.1f} ms)")
                return True
    except Exception as e:
        print(f"  [!] Mihomo 无线隧道配置提示: {e}")
    return False


def detect_network_env():
    """自动检测当前有线 PPPoE/以太网 IPv4、有线 IPv6、无线 WLAN IPv4 状态与网关"""
    ps_script = r"""
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $v4 = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object InterfaceAlias, InterfaceIndex, IPAddress
    $v6 = Get-NetIPAddress -AddressFamily IPv6 | Where-Object { $_.IPAddress -notlike 'fe80*' -and $_.IPAddress -ne '::1' -and $_.IPAddress -notlike 'fd*' } | Select-Object InterfaceAlias, InterfaceIndex, IPAddress
    $gw4 = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object InterfaceAlias, InterfaceIndex, NextHop, RouteMetric
    $gw6 = Get-NetRoute -DestinationPrefix '::/0' | Select-Object InterfaceAlias, InterfaceIndex, NextHop, RouteMetric
    @{ v4=$v4; v6=$v6; gw4=$gw4; gw6=$gw6 } | ConvertTo-Json -Depth 4 -Compress
    """
    env = {
        "wired_v4": None,
        "wired_v4_iface": None,
        "wired_v4_idx": None,
        "wired_v6": None,
        "wired_v6_iface": None,
        "wifi_v4": None,
        "wifi_v4_iface": None,
        "wifi_v4_idx": None,
        "wifi_v4_gw": "10.175.255.254",
    }
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, encoding="utf-8", errors="ignore", timeout=10
        )
        raw_out = (p.stdout or "").strip()
        data = json.loads(raw_out)
        v4_list = data.get("v4") or []
        if isinstance(v4_list, dict):
            v4_list = [v4_list]
        v6_list = data.get("v6") or []
        if isinstance(v6_list, dict):
            v6_list = [v6_list]
        gw4_list = data.get("gw4") or []
        if isinstance(gw4_list, dict):
            gw4_list = [gw4_list]

        for item in v4_list:
            alias = str(item.get("InterfaceAlias", ""))
            ip = str(item.get("IPAddress", ""))
            idx = item.get("InterfaceIndex")
            if "PPPOE" in alias.upper() or ip.startswith("10.192."):
                env["wired_v4"] = ip
                env["wired_v4_iface"] = alias
                env["wired_v4_idx"] = idx
            elif "WLAN" in alias.upper() or "WI-FI" in alias.upper() or ip.startswith("10.175."):
                env["wifi_v4"] = ip
                env["wifi_v4_iface"] = alias
                env["wifi_v4_idx"] = idx

        for gw in gw4_list:
            nh = str(gw.get("NextHop", ""))
            if env["wifi_v4_idx"] and gw.get("InterfaceIndex") == env["wifi_v4_idx"] and nh != "0.0.0.0":
                env["wifi_v4_gw"] = nh
            elif nh.startswith("10.175."):
                env["wifi_v4_gw"] = nh

        for item in v6_list:
            alias = str(item.get("InterfaceAlias", ""))
            ip = str(item.get("IPAddress", ""))
            if ip.startswith("2001:da8:") or ip.startswith("240"):
                env["wired_v6"] = ip
                env["wired_v6_iface"] = alias
                break
    except Exception as e:
        print(f"[!] 网络接口检测警告: {e}")
    return env


def probe_http_node(ip, host, family=socket.AF_INET6, bind_ip=None, ua=STEAM_UA, uri="/depot/457141/chunk/1", timeout=1.3, if_idx=None):
    """使用指定网卡与 User-Agent 探测 Steam CDN 节点的真实 HTTP 响应与延时"""
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        if family == socket.AF_INET and if_idx:
            try:
                s.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", int(if_idx)))
            except Exception:
                pass
        if bind_ip:
            s.bind((bind_ip, 0))
        t0 = time.perf_counter()
        s.connect((ip, 80))
        conn_ms = (time.perf_counter() - t0) * 1000.0
        req = (
            f"GET {uri} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: */*\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("utf-8")
        s.sendall(req)
        data = s.recv(256)
        tot_ms = (time.perf_counter() - t0) * 1000.0
        if not data:
            return {"ok": False, "conn_ms": conn_ms, "tot_ms": tot_ms, "status": "EMPTY_EOF"}
        first_line = data.decode("utf-8", errors="ignore").splitlines()[0].strip()
        return {"ok": first_line.startswith("HTTP/"), "conn_ms": conn_ms, "tot_ms": tot_ms, "status": first_line}
    except Exception as e:
        return {"ok": False, "conn_ms": None, "tot_ms": None, "status": f"{type(e).__name__}: {e}"}
    finally:
        s.close()


def analyze_steam_logs():
    """分析 D:\\steam\\logs 下的 connection_log.txt 与 content_log.txt"""
    report = {
        "ipv6_http_last": None,
        "ipv6_udp_last": None,
        "ipv6_locked_out": False,
        "high_speed_records": [],
        "recent_dpi_timeouts": 0,
        "recent_zero_ip_errors": 0,
        "last_errors": [],
    }
    conn_log = os.path.join(STEAM_LOG_DIR, "connection_log.txt")
    if os.path.exists(conn_log):
        try:
            with open(conn_log, "r", encoding="utf-8", errors="ignore") as f:
                for ln in f:
                    if "IPv6 HTTP connectivity test" in ln:
                        report["ipv6_http_last"] = ln.strip()
                    elif "IPv6 UDP connectivity test" in ln:
                        report["ipv6_udp_last"] = ln.strip()
            if report["ipv6_http_last"] and ("TIMEOUT" in report["ipv6_http_last"] or "FAILED" in report["ipv6_http_last"]):
                report["ipv6_locked_out"] = True
        except Exception:
            pass

    content_log = os.path.join(STEAM_LOG_DIR, "content_log.txt")
    if os.path.exists(content_log):
        try:
            with open(content_log, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
            for ln in lines:
                if "Current download rate:" in ln:
                    try:
                        mbps = float(ln.split("Current download rate:")[1].split("Mbps")[0].strip())
                        if mbps >= 140.0:
                            report["high_speed_records"].append((ln.strip(), mbps, mbps / 8.0))
                    except Exception:
                        pass
                elif "stats: (Invalid, 0)" in ln:
                    m = re.search(r"\(([0-9.]+) Mbps\)", ln)
                    if m and float(m.group(1)) >= 140.0:
                        mbps = float(m.group(1))
                        report["high_speed_records"].append((ln.strip(), mbps, mbps / 8.0))

            for ln in lines[-400:]:
                if "received 0 (Invalid) HTTP response" in ln or "Received 0 (Invalid) HTTP response" in ln:
                    report["recent_dpi_timeouts"] += 1
                    report["last_errors"].append(ln.strip())
                elif "(0.0.0.0:80 / 0.0.0.0:80" in ln and ("failed to send" in ln or "No Connection" in ln):
                    report["recent_zero_ip_errors"] += 1
                    report["last_errors"].append(ln.strip())
        except Exception:
            pass
    return report


def run_dpi_comparison(env):
    """实测对比：有线 IPv4 vs 有线 IPv6 vs 无线 IPv4 在 Steam 真实 UA 下的 L7 DPI 拦截表现"""
    print("\n" + "=" * 78)
    print(" [模块 2] 三通道 Steam 协议栈 L7 DPI 深度包检测实测 (Steam UA vs 浏览器 UA)")
    print("=" * 78)
    test_host = "st.dl.eccdnx.com"
    test_v4 = "39.137.15.123"
    test_v6 = "240e:bf:b800:1e00::c"

    if env["wired_v4"]:
        r_steam = probe_http_node(test_v4, test_host, socket.AF_INET, env["wired_v4"], STEAM_UA, timeout=1.3, if_idx=env.get("wired_v4_idx"))
        r_brow = probe_http_node(test_v4, test_host, socket.AF_INET, env["wired_v4"], BROWSER_UA, timeout=1.3, if_idx=env.get("wired_v4_idx"))
        print(f"  1. 有线 IPv4 ({env['wired_v4_iface']} {env['wired_v4']}) -> {test_host} ({test_v4}:80):")
        print(f"     - 携带 Steam 官方 UA ({STEAM_UA}): {'[通过] ' + r_steam['status'] if r_steam['ok'] else '[被校园网 DPI 拦截丢包!] ' + r_steam['status']}")
        if r_brow["ok"]:
            print(f"     - 伪装浏览器 UA (Mozilla/5.0):        [通过] {r_brow['status']} (耗时 {r_brow['tot_ms']:.1f} ms)")
            if not r_steam["ok"]:
                print("     => 【实证结论】有线拨号 IPv4 出口存在精确匹配 'Valve/Steam HTTP Client 1.0' 的 L7 DPI 黑洞！")

    if env["wired_v6"]:
        r_v6 = probe_http_node(test_v6, "dl.steam.clngaa.com", socket.AF_INET6, None, STEAM_UA, timeout=1.3)
        print(f"  2. 有线 IPv6 ({env['wired_v6_iface']} {env['wired_v6'][:22]}...) -> dl.steam.clngaa.com ([{test_v6}]:80):")
        if r_v6["ok"]:
            print(f"     - 携带 Steam 官方 UA ({STEAM_UA}): [零拦截极速通过!] {r_v6['status']} (TCP握手 {r_v6['conn_ms']:.1f} ms / 总耗时 {r_v6['tot_ms']:.1f} ms)")
        else:
            print(f"     - 探测失败: {r_v6['status']}")

    if env["wifi_v4"]:
        r_wifi = probe_http_node(test_v4, test_host, socket.AF_INET, env["wifi_v4"], STEAM_UA, timeout=1.3, if_idx=env.get("wifi_v4_idx"))
        print(f"  3. 无线 IPv4 ({env['wifi_v4_iface']} {env['wifi_v4']}) -> {test_host} ({test_v4}:80):")
        if r_wifi["ok"]:
            print(f"     - 携带 Steam 官方 UA ({STEAM_UA}): [零拦截极速通过!] {r_wifi['status']} (TCP握手 {r_wifi['conn_ms']:.1f} ms / 总耗时 {r_wifi['tot_ms']:.1f} ms)")
        else:
            print(f"     - 探测失败: {r_wifi['status']}")


def scan_best_nodes(env):
    """多线程并发扫描所有候选 IPv6 门禁与 CDN 节点的真实 Steam HTTP 响应延迟"""
    print("\n" + "=" * 78)
    print(" [模块 3] Steam 全量 CDN 节点与 IPv6 门禁并发优选 (真实 Steam HTTP 协议栈握手)")
    print("=" * 78)

    bind_v4 = env["wifi_v4"]
    v4_tag = f"无线 {bind_v4}" if bind_v4 else "默认 IPv4"

    with ThreadPoolExecutor(max_workers=16) as ex:
        gk_futures = [
            (label, ip, ex.submit(probe_http_node, ip, "ipv6check-http.steamserver.net", socket.AF_INET6, None, STEAM_UA, "/", 1.3))
            for label, ip in IPV6_GATEKEEPER_CANDIDATES
        ]
        cdn_futures = {}
        for domain, info in CDN_CANDIDATES.items():
            v6_futs = [
                (label, ip, ex.submit(probe_http_node, ip, domain, socket.AF_INET6, None, STEAM_UA, "/depot/457141/chunk/1", 1.3))
                for label, ip in info.get("v6", [])
            ]
            v4_futs = [
                (label, ip, ex.submit(probe_http_node, ip, domain, socket.AF_INET, bind_v4, STEAM_UA if bind_v4 else BROWSER_UA, "/depot/457141/chunk/1", 1.3, env.get("wifi_v4_idx") if bind_v4 else env.get("wired_v4_idx")))
                for label, ip in info.get("v4", [])
            ]
            cdn_futures[domain] = (info, v6_futs, v4_futs)

    best_gatekeeper_v6 = None
    best_gk_ms = 99999.0
    print("\n  [A] Steam IPv6 门禁服务器 (ipv6check-*.steamserver.net) 测速结果:")
    for label, ip, fut in gk_futures:
        res = fut.result()
        if res["ok"]:
            print(f"      [OK] {label:24s} | {ip:28s} | {res['tot_ms']:6.1f} ms | {res['status']}")
            if res["tot_ms"] < best_gk_ms:
                best_gk_ms = res["tot_ms"]
                best_gatekeeper_v6 = ip
        else:
            print(f"      [--] {label:24s} | {ip:28s} | 超时/不可达")

    best_cdn = {}
    for domain, (info, v6_futs, v4_futs) in cdn_futures.items():
        print(f"\n  [B] {domain} ({info['desc']}):")
        best_v6 = None
        best_v6_ms = 99999.0
        for label, ip, fut in v6_futs:
            res = fut.result()
            if res["ok"]:
                print(f"      [IPv6 OK] {label:24s} | {ip:28s} | {res['tot_ms']:6.1f} ms | {res['status']}")
                if res["tot_ms"] < best_v6_ms:
                    best_v6_ms = res["tot_ms"]
                    best_v6 = ip
            else:
                print(f"      [IPv6 --] {label:24s} | {ip:28s} | 失败 ({res['status'][:28]})")

        best_v4 = None
        best_v4_ms = 99999.0
        for label, ip, fut in v4_futs:
            res = fut.result()
            if res["ok"]:
                print(f"      [IPv4 OK] {label:24s} | {ip:28s} | {res['tot_ms']:6.1f} ms ({v4_tag}) | {res['status']}")
                if res["tot_ms"] < best_v4_ms:
                    best_v4_ms = res["tot_ms"]
                    best_v4 = ip
            else:
                print(f"      [IPv4 --] {label:24s} | {ip:28s} | 失败 ({v4_tag})")

        best_cdn[domain] = {
            "v6": best_v6 or (info["v6"][0][1] if info.get("v6") else None),
            "v6_ms": best_v6_ms,
            "v4": best_v4 or (info["v4"][0][1] if info.get("v4") else None),
            "v4_ms": best_v4_ms,
            "role_dual": info["role_dual"],
            "tunnel_ip": info.get("tunnel_ip"),
            "desc": info["desc"],
        }

    return best_gatekeeper_v6 or "2404:3fc0:a:100::10", best_cdn


def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}



class SteamTripleStackProxy:
    """
    Steam 三端超叠加 + 有线 IPv4 DPI 绕过透明反向代理引擎 (v2.0)
    -------------------------------------------------------------------------
    工作原理 (移植并增强自 Xidian_MultiNet_Proxy.py):
      1. 在本地回环地址 127.0.0.31 ~ 127.0.0.37:80 监听 7 个 Steam 主力 CDN 域名；
      2. 接收 Steam 客户端发起的并发 HTTP Chunk 连接，按 10 槽位加权轮询 (Per-Connection Round-Robin)
         动态分发至以下三条独立物理通道：
         - [W_V6] 有线 IPv6 (教育网 CERNET2 100M, 40% 权重, 槽位 0,3,6,8):
                  AF_INET6 直连 CDN AAAA 极速节点；
         - [W_V4] 有线 IPv4 (陕西移动 CMCC_PPPOE 100M, 30% 权重, 槽位 1,4,7):
                  通过 Windows IP_UNICAST_IF (31) 强绑有线网卡 + 流式重写 HTTP 请求头中的
                  'User-Agent: Valve/Steam HTTP Client 1.0' -> 'User-Agent: Mozilla/5.0 ...'
                  结合 TCP_NODELAY 彻底绕过西电有线校园网针对 Steam 的 L7 DPI 0字节黑洞！
         - [L_V4] 无线 IPv4 (无线校园网 WLAN 100M, 30% 权重, 槽位 2,5,9):
                  通过 Windows IP_UNICAST_IF (31) 强绑无线网卡直连 CDN A 记录节点。
      3. 支持【单网线双栈模式 (wiredds)】:
         当未连接无线 Wi-Fi 时，自动按 50% W_V6 (有线 IPv6) + 50% W_V4 (有线 IPv4 DPI绕过)
         轮询叠加，单根网线即可跑出 ~20+ MB/s 的双倍下载速度！
    """

    def __init__(self, proxy_mode="triplestack", env=None, quiet=False):
        self.proxy_mode = proxy_mode  # "triplestack" (4:3:3) or "wiredds" (5:5)
        self.env = env or detect_network_env()
        self.quiet = quiet
        self.running = True
        self.rr_lock = threading.Lock()
        self.rr_counter = 0
        self.stats_lock = threading.Lock()
        self.bytes_stats = {"W_V6": 0, "W_V4": 0, "L_V4": 0}
        self.conn_stats = {"W_V6": 0, "W_V4": 0, "L_V4": 0}
        self.servers = []

    def pick_channel_order(self):
        with self.rr_lock:
            slot = self.rr_counter % 10
            self.rr_counter += 1

        has_v6 = bool(self.env.get("wired_v6"))
        has_w4 = bool(self.env.get("wired_v4"))
        has_l4 = bool(self.env.get("wifi_v4")) and self.proxy_mode == "triplestack"

        if has_v6 and has_w4 and has_l4:
            if slot in (0, 3, 6, 8):
                return ["W_V6", "W_V4", "L_V4"]
            elif slot in (1, 4, 7):
                return ["W_V4", "W_V6", "L_V4"]
            else:
                return ["L_V4", "W_V6", "W_V4"]
        elif has_v6 and has_w4:
            return ["W_V6", "W_V4"] if (slot % 2 == 0) else ["W_V4", "W_V6"]
        elif has_v6 and has_l4:
            return ["W_V6", "L_V4"] if (slot % 2 == 0) else ["L_V4", "W_V6"]
        elif has_w4 and has_l4:
            return ["W_V4", "L_V4"] if (slot % 2 == 0) else ["L_V4", "W_V4"]
        elif has_v6:
            return ["W_V6"]
        elif has_w4:
            return ["W_V4"]
        else:
            return ["L_V4"]

    def open_outbound_socket(self, domain, port=80):
        targets = TRIPLE_PROXY_DEFAULT_MATRIX.get(domain, TRIPLE_PROXY_DEFAULT_MATRIX["dl.steam.clngaa.com"])
        order = self.pick_channel_order()

        for ch in order:
            dst_ip = targets.get(ch)
            if not dst_ip:
                continue
            fam = socket.AF_INET6 if ":" in dst_ip else socket.AF_INET
            s = None
            try:
                s = socket.socket(fam, socket.SOCK_STREAM)
                s.settimeout(2.5)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                except Exception:
                    pass

                if ch == "W_V4":
                    if_idx = self.env.get("wired_v4_idx")
                    bind_ip = self.env.get("wired_v4")
                    if if_idx:
                        s.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", int(if_idx)))
                    if bind_ip:
                        s.bind((bind_ip, 0))
                elif ch == "L_V4":
                    if_idx = self.env.get("wifi_v4_idx")
                    bind_ip = self.env.get("wifi_v4")
                    if if_idx:
                        s.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", int(if_idx)))
                    if bind_ip:
                        s.bind((bind_ip, 0))

                s.connect((dst_ip, port))
                s.settimeout(30.0)
                with self.stats_lock:
                    self.conn_stats[ch] = self.conn_stats.get(ch, 0) + 1
                return s, ch
            except Exception:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
        return None, None

    def handle_client(self, client_sock, default_domain, port=80):
        remote_sock = None
        try:
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            except Exception:
                pass
            client_sock.settimeout(15.0)
            first_chunk = client_sock.recv(16384)
            if not first_chunk:
                client_sock.close()
                return

            domain = default_domain
            if port == 80:
                m = re.search(rb"(?im)^Host:\s*([^\r\n:]+)", first_chunk)
                if m:
                    parsed_dom = m.group(1).decode("ascii", errors="ignore").strip().lower()
                    if parsed_dom in TRIPLE_PROXY_DEFAULT_MATRIX:
                        domain = parsed_dom

            remote_sock, ch = self.open_outbound_socket(domain, port)
            if not remote_sock:
                client_sock.close()
                return

            rewrite_ua = (ch == "W_V4" and port == 80)
            if rewrite_ua and b"Valve/Steam" in first_chunk:
                first_chunk = re.sub(
                    rb"(?i)User-Agent:\s*Valve/Steam[^\r\n]*",
                    b"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    first_chunk,
                )
            remote_sock.sendall(first_chunk)

            def req_pipe():
                try:
                    while self.running:
                        data = client_sock.recv(16384)
                        if not data:
                            break
                        if rewrite_ua and b"Valve/Steam" in data:
                            data = re.sub(
                                rb"(?i)User-Agent:\s*Valve/Steam[^\r\n]*",
                                b"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                data,
                            )
                        remote_sock.sendall(data)
                except Exception:
                    pass
                finally:
                    try:
                        remote_sock.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            t_up = threading.Thread(target=req_pipe, daemon=True)
            t_up.start()

            while self.running:
                resp = remote_sock.recv(65536)
                if not resp:
                    break
                client_sock.sendall(resp)
                with self.stats_lock:
                    self.bytes_stats[ch] = self.bytes_stats.get(ch, 0) + len(resp)
        except Exception:
            pass
        finally:
            for sk in (client_sock, remote_sock):
                if sk:
                    try:
                        sk.close()
                    except Exception:
                        pass

    def serve_forever(self):
        for dom, listen_ip in TRIPLE_PROXY_LISTEN_MAP.items():
            for port in (80,):
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind((listen_ip, port))
                srv.listen(256)
                self.servers.append(srv)

                def accept_loop(s=srv, d=dom, p=port):
                    while self.running:
                        try:
                            cli, _ = s.accept()
                            threading.Thread(target=self.handle_client, args=(cli, d, p), daemon=True).start()
                        except Exception:
                            if not self.running:
                                break

                threading.Thread(target=accept_loop, daemon=True).start()

        if not self.quiet:
            print("\n" + "=" * 78)
            print(f" [Steam 三端叠加 + DPI 绕过透明反向代理已启动] 模式: {self.proxy_mode}")
            print(f" 监听地址: 127.0.0.31 ~ 127.0.0.37:80 | PID: {os.getpid()}")
            print(f" 通道状态: W_V6(有线IPv6)={bool(self.env.get('wired_v6'))} | "
                  f"W_V4(有线IPv4 DPI绕过)={self.env.get('wired_v4')} | "
                  f"L_V4(无线IPv4)={self.env.get('wifi_v4')}")
            print("=" * 78)

        last_b = dict(self.bytes_stats)
        last_t = time.perf_counter()
        try:
            while self.running:
                time.sleep(1.0)
                now = time.perf_counter()
                dt = max(0.1, now - last_t)
                last_t = now
                with self.stats_lock:
                    cur_b = dict(self.bytes_stats)
                    cur_c = dict(self.conn_stats)
                r_v6 = (cur_b["W_V6"] - last_b["W_V6"]) / 1048576.0 / dt
                r_w4 = (cur_b["W_V4"] - last_b["W_V4"]) / 1048576.0 / dt
                r_l4 = (cur_b["L_V4"] - last_b["L_V4"]) / 1048576.0 / dt
                last_b = cur_b
                tot = r_v6 + r_w4 + r_l4
                if not self.quiet and (tot > 0.01 or sum(cur_c.values()) > 0):
                    tot_gb = sum(cur_b.values()) / (1024 ** 3)
                    sys.stdout.write(
                        f"\r [实时速率] 总计: {tot:6.2f} MB/s ({tot*8:5.1f}M) | "
                        f"有线IPv6: {r_v6:5.2f} MB/s | 有线IPv4(DPI绕过): {r_w4:5.2f} MB/s | "
                        f"无线IPv4: {r_l4:5.2f} MB/s | 累计: {tot_gb:.2f} GB   "
                    )
                    sys.stdout.flush()
        except KeyboardInterrupt:
            self.running = False


def stop_triple_proxy_daemon():
    """停止后台运行的 Steam 三端叠加本地反向代理守护进程 (127.0.0.31~37:80)"""
    killed_pids = set()
    prev = load_previous_state()
    rec_pid = prev.get("triple_proxy_pid")
    if rec_pid:
        try:
            r = subprocess.run(["taskkill", "/F", "/PID", str(rec_pid)], capture_output=True, text=True)
            if r.returncode == 0:
                killed_pids.add(int(rec_pid))
        except Exception:
            pass

    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="gbk", errors="ignore")
        for ln in r.stdout.splitlines():
            if "127.0.0.31:80" in ln and "LISTENING" in ln:
                parts = ln.split()
                pid = int(parts[-1])
                if pid > 0 and pid != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                    killed_pids.add(pid)
    except Exception:
        pass

    if killed_pids:
        print(f"  [+] 已停止上次驻留的 Steam 三端叠加反向代理进程 (PID: {', '.join(map(str, sorted(killed_pids)))})。")
        time.sleep(0.3)
    return True


def start_triple_proxy_daemon(proxy_mode="triplestack"):
    """在后台无窗口启动 Steam 三端叠加本地反向代理守护进程 (127.0.0.31~37:80)"""
    stop_triple_proxy_daemon()
    CREATE_NO_WINDOW = 0x08000000
    cmd = [sys.executable, os.path.abspath(__file__), "--run-proxy-daemon", "--proxy-mode", proxy_mode]
    log_f = open(PROXY_LOG_FILE, "a", encoding="utf-8", errors="ignore")
    proc = subprocess.Popen(
        cmd,
        stdout=log_f,
        stderr=log_f,
        creationflags=CREATE_NO_WINDOW,
        close_fds=False,
    )
    for _ in range(25):
        time.sleep(0.15)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            if s.connect_ex(("127.0.0.31", 80)) == 0:
                s.close()
                print(f"  [+] Steam 三端叠加 + DPI 绕过后台反代已启动 (PID={proc.pid}, 监听 127.0.0.31~37:80, 模式={proxy_mode})。")
                return proc.pid
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    print("  [!] 警告：Steam 三端叠加后台反代启动超时，请检查 80 端口占用情况。")
    return None


def save_current_state(mode, entries, routes, tunnels, env, triple_proxy_pid=None):
    state = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "2.0",
        "mode": mode,
        "triple_proxy_pid": triple_proxy_pid,
        "network_snapshot": env,
        "mihomo_wlan_tunnels": tunnels,
        "injected_routes": [{"subnet": n, "mask": m, "gateway": env.get("wifi_v4_gw"), "if_index": env.get("wifi_v4_idx")} for n, m in routes],
        "injected_hosts": [{"ip": ip, "domain": dom, "comment": cmt} for ip, dom, cmt in entries],
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [!] 状态记录保存警告: {e}")


def apply_wifi_routes(env, clear_only=False):
    """配置或清理将 Steam IPv4 CDN 网段指向无线网卡 stu-xdwlan 的静态路由"""
    prev = load_previous_state()
    prev_nets = {item.get("subnet") for item in prev.get("injected_routes", []) if item.get("subnet")}
    all_nets_to_clean = prev_nets | {net for net, _ in STEAM_IPV4_SUBNETS}
    for net in sorted(all_nets_to_clean):
        subprocess.run(["route", "delete", net], capture_output=True)

    if clear_only:
        print(f"  [+] 已清理上次记录与内置列表中的全部 {len(all_nets_to_clean)} 条 Steam 专用无线 IPv4 静态路由。")
        return True

    if not env["wifi_v4"] or not env["wifi_v4_idx"]:
        return False

    gw = env["wifi_v4_gw"]
    idx = str(env["wifi_v4_idx"])
    ok_cnt = 0
    for net, mask in STEAM_IPV4_SUBNETS:
        r = subprocess.run(
            ["route", "add", net, "mask", mask, gw, "metric", "1", "IF", idx],
            capture_output=True, encoding="utf-8", errors="ignore"
        )
        if r.returncode == 0:
            ok_cnt += 1
    if ok_cnt > 0:
        print(f"  [+] 已成功注入 {ok_cnt}/{len(STEAM_IPV4_SUBNETS)} 条 Windows 底层无线静态路由 -> {env['wifi_v4_iface']} (网关 {gw}, IF {idx})。")
        return True
    return False


def update_hosts_file(entries, clear_only=False):
    """安全更新系统 Hosts 文件，同时清理旧版 UsbEAm 残留的 Steam #UHE_ 条目避免冲突"""
    hosts_path = get_system_hosts_path()
    with open(hosts_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()

    cleaned = []
    in_block = False
    steam_keywords = set(CDN_CANDIDATES.keys()) | set(IPV6_GATEKEEPER_DOMAINS) | {"st.dl.bscstorage.net", "dl.steam.clngaa.com"}

    for ln in lines:
        s = ln.strip()
        if s == HOSTS_TAG_START:
            in_block = True
            continue
        if s == HOSTS_TAG_END:
            in_block = False
            continue
        if in_block:
            continue
        if "#UHE_" in ln and any(k in ln for k in steam_keywords):
            continue
        cleaned.append(ln)

    while cleaned and cleaned[-1].strip() == "":
        cleaned.pop()

    if not clear_only and entries:
        cleaned.append("")
        cleaned.append(HOSTS_TAG_START)
        cleaned.append(f"# Updated by Xidian Steam Dual-Stack Optimizer v1.2 at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        for ip, dom, comment in entries:
            cleaned.append(f"{ip:32s} {dom:34s} # {comment}")
        cleaned.append(HOSTS_TAG_END)
        cleaned.append("")

    content = "\n".join(cleaned) + "\n"
    with open(hosts_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)

    subprocess.run(["ipconfig", "/flushdns"], capture_output=True)


def run_dualstack_speedtest(env):
    """实测当前有线 IPv6 (通道A: dl.steam.clngaa.com) + 无线 IPv4 (通道B: st.dl.eccdnx.com) 并发下载总吞吐量"""
    print("\n" + "=" * 78)
    print(" [模块 4] Steam CDN 双栈双主力通道 (有线 IPv6 clngaa + 无线 IPv4 eccdnx) 并发吞吐实测")
    print("=" * 78)
    content_log = os.path.join(STEAM_LOG_DIR, "content_log.txt")
    uri_cln = None
    uri_ecc = None
    if os.path.exists(content_log):
        with open(content_log, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        cln_matches = [u.rstrip("\"'") for u in re.findall(r"dl\.steam\.clngaa\.com(/depot/457141/\S+)", text)]
        if not cln_matches:
            cln_matches = [u.rstrip("\"'") for u in re.findall(r"dl\.steam\.clngaa\.com(/depot/\S+)", text)]
        if cln_matches:
            uri_cln = cln_matches[-1]

        ecc_matches = [u.rstrip("\"'") for u in re.findall(r"st\.dl\.eccdnx\.com(/depot/457141/\S+)", text)]
        if not ecc_matches:
            ecc_matches = [u.rstrip("\"'") for u in re.findall(r"st\.dl\.eccdnx\.com(/depot/\S+)", text)]
        if ecc_matches:
            uri_ecc = ecc_matches[-1]

    if not uri_cln and not uri_ecc:
        print("  [i] 未在近期日志中找到活动 Patch/Chunk Token，跳过大文件拉取测速。")
        return

    uri_cln = uri_cln or uri_ecc
    uri_ecc = uri_ecc or uri_cln

    b_v6 = [0]
    b_v4 = [0]
    stop = [False]

    tunnel_active = probe_http_node("127.0.0.21", "st.dl.eccdnx.com", socket.AF_INET, None, STEAM_UA, "/depot/457141/chunk/1", 1.2)["ok"]

    def worker_v6():
        while not stop[0]:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s.settimeout(3.0)
            try:
                s.connect(("240e:bf:b800:1e00::c", 80))
                req = f"GET {uri_cln} HTTP/1.1\r\nHost: dl.steam.clngaa.com\r\nUser-Agent: {STEAM_UA}\r\nConnection: close\r\n\r\n".encode()
                s.sendall(req)
                while not stop[0]:
                    d = s.recv(65536)
                    if not d:
                        break
                    b_v6[0] += len(d)
            except Exception:
                break
            finally:
                s.close()

    def worker_v4(target_ip, use_bind):
        while not stop[0]:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3.0)
            try:
                if use_bind and env["wifi_v4"]:
                    s.bind((env["wifi_v4"], 0))
                s.connect((target_ip, 80))
                req = f"GET {uri_ecc} HTTP/1.1\r\nHost: st.dl.eccdnx.com\r\nUser-Agent: {STEAM_UA}\r\nConnection: close\r\n\r\n".encode()
                s.sendall(req)
                while not stop[0]:
                    d = s.recv(65536)
                    if not d:
                        break
                    b_v4[0] += len(d)
            except Exception:
                break
            finally:
                s.close()

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker_v6) for _ in range(4)]
    if tunnel_active:
        threads += [threading.Thread(target=worker_v4, args=("127.0.0.21", False)) for _ in range(3)]
        threads += [threading.Thread(target=worker_v4, args=("127.0.0.22", False)) for _ in range(3)]
    elif env["wifi_v4"]:
        for ip in ("219.144.24.94", "61.150.82.31", "203.2.166.83", "113.14.6.143"):
            threads.append(threading.Thread(target=worker_v4, args=(ip, True)))

    for t in threads:
        t.start()
    time.sleep(4.2)
    stop[0] = True
    for t in threads:
        t.join(timeout=1.0)
    dt = max(0.1, time.perf_counter() - t0)
    s6 = b_v6[0] / (1024 * 1024) / dt
    s4 = b_v4[0] / (1024 * 1024) / dt
    tot = s6 + s4
    v4_mode_str = "Mihomo本地隧道 127.0.0.21 -> WLAN -> 219.144.24.94" if tunnel_active else f"WLAN {env['wifi_v4']} -> 219.144.24.94"
    print(f"  - 通道 A [有线 IPv6 -> dl.steam.clngaa.com (240e:bf:b800:1e00::c)]: {s6:6.2f} MB/s ({s6*8.0:6.1f} Mbps)")
    if tunnel_active or env["wifi_v4"]:
        print(f"  - 通道 B [无线 IPv4 -> st.dl.eccdnx.com ({v4_mode_str})]: {s4:6.2f} MB/s ({s4*8.0:6.1f} Mbps)")
    print(f"  => 【Steam 双主力 CDN 双栈叠加实测总速度】:                        {tot:6.2f} MB/s ({tot*8.0:6.1f} Mbps)")


def print_full_diagnosis(env):
    print("=" * 78)
    print(" [模块 1] 当前多网卡环境与 Steam 日志全链路诊断")
    print("=" * 78)
    print(f"  - 有线 IPv4 网卡: {env['wired_v4_iface'] or '未连接'} ({env['wired_v4'] or '无'})")
    print(f"  - 有线 IPv6 网卡: {env['wired_v6_iface'] or '未连接'} ({env['wired_v6'] or '无'})")
    print(f"  - 无线 IPv4 网卡: {env['wifi_v4_iface'] or '未连接'} ({env['wifi_v4'] or '无'}, 网关 {env['wifi_v4_gw']}, IF={env['wifi_v4_idx']})")

    log_rep = analyze_steam_logs()
    print("\n  [Steam 客户端内部状态体检 (D:\\steam\\logs)]:")
    print(f"  - 最近一次 IPv6 HTTP 门禁自检: {log_rep['ipv6_http_last'] or '未记录'}")
    print(f"  - 最近一次 IPv6 UDP  门禁自检: {log_rep['ipv6_udp_last'] or '未记录'}")
    if log_rep["ipv6_locked_out"]:
        print("  - [!!! 严重告警 !!!] Steam 启动时 ipv6check 自检超时/解析失败，当前 Steam 进程内部已强行关闭 IPv6 下载栈！")
    else:
        print("  - [正常] Steam 内部 IPv6 门禁状态已激活。")

    print(f"  - 近期因有线 IPv4 DPI 黑洞导致的 HTTP 超时次数: {log_rep['recent_dpi_timeouts']} 次")
    print(f"  - 近期因 IPv6 门禁锁死导致的 0.0.0.0:80 失败次数: {log_rep['recent_zero_ip_errors']} 次")
    if log_rep["high_speed_records"]:
        print("  - 历史双栈并发 (>140 Mbps) 峰值记录:")
        for raw, mbps, mbs in log_rep["high_speed_records"][-5:]:
            print(f"      * {mbps:6.2f} Mbps ({mbs:5.2f} MB/s) | {raw[:75]}")

    run_dpi_comparison(env)


def apply_mode(mode, env):
    gk_v6, best_cdn = scan_best_nodes(env)
    entries = []
    for gk_dom in IPV6_GATEKEEPER_DOMAINS:
        entries.append((gk_v6, gk_dom, "Steam IPv6 Gatekeeper Keep-Alive"))

    if mode == "dualstack" and not env["wifi_v4"]:
        print("\n  [!] 警告：未检测到无线网卡连接，自动降级为【全量 IPv6 加速模式】。")
        mode = "ipv6only"

    tunnel_ok = False
    routes_ok = False
    tunnels_saved = []

    if mode == "dualstack":
        print("\n" + "=" * 78)
        print(" [执行写入] 正在应用【有线 IPv6 (100M) + 无线 IPv4 (100M) 双栈超叠加模式 v1.2】")
        print("=" * 78)
        tunnel_ok = ensure_mihomo_steam_tunnels(best_cdn, clear_only=False)
        routes_ok = apply_wifi_routes(env, clear_only=False)
        if not tunnel_ok and not routes_ok:
            print("  [!] 警告：Mihomo 隧道与管理员静态路由均未就绪，为防止有线 IPv4 DPI 0字节断流，回退至纯 IPv6 模式。")
            mode = "ipv6only"
        else:
            for dom, info in best_cdn.items():
                if info["role_dual"] == "v4" and info["v4"]:
                    if tunnel_ok and info.get("tunnel_ip"):
                        entries.append((
                            info["tunnel_ip"],
                            dom,
                            f"Channel-B WiFi-IPv4 Tunnel -> {info['v4']} via WLAN ({info['v4_ms']:.1f}ms)",
                        ))
                        tunnels_saved.append({"domain": dom, "listen": info["tunnel_ip"], "target": info["v4"], "proxy": WLAN_PROXY_NAME})
                    elif routes_ok:
                        entries.append((
                            info["v4"],
                            dom,
                            f"Channel-B WiFi-IPv4 Route via {env['wifi_v4_gw']} ({info['v4_ms']:.1f}ms)",
                        ))
                elif info["v6"]:
                    entries.append((
                        info["v6"],
                        dom,
                        f"Channel-A Wired-IPv6 CERNET2 ({info['v6_ms']:.1f}ms)",
                    ))

    triple_pid = None
    if mode in ("dualstack", "ipv6only"):
        stop_triple_proxy_daemon()

    if mode in ("triplestack", "wiredds"):
        mode_title = (
            "【三端超叠加 + 有线 IPv4 DPI 绕过模式 v2.0 (有线IPv6 40% + 有线IPv4[UA伪装] 30% + 无线IPv4 30%)】"
            if mode == "triplestack"
            else "【单网线双栈叠加 + DPI 绕过模式 v2.0 (有线IPv6 50% + 有线IPv4[UA伪装] 50%)】"
        )
        print("\n" + "=" * 78)
        print(f" [执行写入] 正在应用 {mode_title}")
        print("=" * 78)
        ensure_mihomo_steam_tunnels({}, clear_only=True)
        apply_wifi_routes(env, clear_only=True)
        triple_pid = start_triple_proxy_daemon(proxy_mode=mode)
        if not triple_pid:
            print("  [!] 警告：本地三端反代未能绑定 80 端口，自动回退至双栈模式 (dualstack)。")
            mode = "dualstack"
        else:
            for dom, tip in TRIPLE_PROXY_LISTEN_MAP.items():
                m_cfg = TRIPLE_PROXY_DEFAULT_MATRIX[dom]
                cmt = (
                    f"TripleStack 4:3:3 [V6:{m_cfg['W_V6']} | W_V4(DPI-Bypass):{m_cfg['W_V4']} | L_V4:{m_cfg['L_V4']}]"
                    if mode == "triplestack"
                    else f"WiredDualStack 5:5 [V6:{m_cfg['W_V6']} | W_V4(DPI-Bypass):{m_cfg['W_V4']}]"
                )
                entries.append((tip, dom, cmt))
                tunnels_saved.append({"domain": dom, "listen": tip, "mode": mode, "targets": m_cfg})

    if mode == "ipv6only":
        print("\n" + "=" * 78)
        print(" [执行写入] 正在应用【纯有线 IPv6 教育网省流加速模式 (零无线防 DPI 0字节)】")
        print("=" * 78)
        ensure_mihomo_steam_tunnels({}, clear_only=True)
        apply_wifi_routes(env, clear_only=True)
        for dom, info in best_cdn.items():
            if info["v6"]:
                entries.append((info["v6"], dom, f"Pure-IPv6 Channel ({info['v6_ms']:.1f}ms)"))

    update_hosts_file(entries, clear_only=False)
    save_current_state(
        mode=mode,
        entries=entries,
        routes=STEAM_IPV4_SUBNETS if (mode == "dualstack" and routes_ok) else [],
        tunnels=tunnels_saved,
        env=env,
        triple_proxy_pid=triple_pid,
    )
    print("\n  [+] 已成功写入系统 Hosts 并刷新 DNS 缓存！当前生效规则如下：")
    for ip, dom, cmt in entries:
        print(f"      {ip:30s} -> {dom:32s} [{cmt}]")
    print("\n  [★ 提示] 双栈分流已实时生效！您只需在 Steam 下载页面点击【继续下载/恢复】即可触发：")
    print("           - 通道 A (有线 IPv6 100M): dl.steam.clngaa.com / yif.gdtstream.com (~11.4 MB/s)")
    print("           - 通道 B (无线 IPv4 100M): st.dl.eccdnx.com / smogfly / manlaxy / pphimalayanrt (~10.7 MB/s)")
    print("           双通道并发总下载速度可达 20 ~ 23+ MB/s (165 ~ 185 Mbps)！")


def interactive_menu():
    os.system("title 西电校园网 Steam 双栈/三端超叠加加速与 CDN 智能优选工具 v2.0")
    while True:
        env = detect_network_env()
        prev = load_previous_state()
        cur_mode = prev.get("mode", "未配置")
        cur_pid = prev.get("triple_proxy_pid")
        print("\n" + "=" * 78)
        print("   西电校园网 Steam 双栈/三端超叠加加速与 CDN 智能优选工具 (v2.0)")
        print("   融合架构: UsbEAm Hosts Editor + XDM 三通道按连接轮询反代 + 有线 IPv4 DPI 绕过")
        print("=" * 78)
        print(f" 当前网卡: 有线IPv4={env['wired_v4'] or '未连接'}(IF={env['wired_v4_idx']}) | 有线IPv6={'已连接(CERNET2)' if env['wired_v6'] else '未连接'} | 无线IPv4={env['wifi_v4'] or '未连接'}(IF={env['wifi_v4_idx']})")
        print(f" 当前模式: {cur_mode}" + (f" (三端反代后台进程 PID={cur_pid})" if cur_pid else ""))
        print("-" * 78)
        print("  [1] 全面体检：诊断 Steam 双栈状态、有线 IPv4 DPI 黑洞实测、日志峰值与并发测速")
        print("  [2] 一键开启：【有线 IPv6 + 无线 IPv4 双端免驻留模式 v1.2】（无后台进程，实测 23.3~24.9 MB/s）")
        print("  [3] 一键开启：【三端超叠加 + 有线 IPv4 DPI 绕过模式 v2.0】（有线IPv6 + 有线IPv4[UA伪装] + 无线IPv4 4:3:3 轮询）")
        print("  [4] 一键开启：【单网线双栈叠加 + DPI 绕过模式 v2.0】（不连Wi-Fi时推荐！单网线有线IPv6 + 有线IPv4 叠加达 ~21 MB/s）")
        print("  [5] 一键开启：【纯有线 IPv6 教育网省流加速模式】（零 IPv4 流量消耗、无后台进程）")
        print("  [6] 一键关闭：彻底清理所有 Steam Hosts、三端反代后台进程、Mihomo 隧道与静态路由（恢复默认）")
        print("  [0] 退出程序")
        print("=" * 78)
        choice = input(" 请输入选项编号 [0-6]: ").strip()
        if choice == "1":
            print_full_diagnosis(env)
            scan_best_nodes(env)
            run_dualstack_speedtest(env)
            input("\n 按回车键返回主菜单...")
        elif choice == "2":
            apply_mode("dualstack", env)
            run_dualstack_speedtest(env)
            input("\n 按回车键返回主菜单...")
        elif choice == "3":
            apply_mode("triplestack", env)
            input("\n 按回车键返回主菜单...")
        elif choice == "4":
            apply_mode("wiredds", env)
            input("\n 按回车键返回主菜单...")
        elif choice == "5":
            apply_mode("ipv6only", env)
            input("\n 按回车键返回主菜单...")
        elif choice == "6":
            stop_triple_proxy_daemon()
            ensure_mihomo_steam_tunnels({}, clear_only=True)
            apply_wifi_routes(env, clear_only=True)
            update_hosts_file([], clear_only=True)
            save_current_state("cleared", [], [], [], env, triple_proxy_pid=None)
            print("  [+] 已彻底停止三端反代后台进程，并清除所有 Steam Hosts、Mihomo 无线隧道与静态路由，恢复系统默认。")
            input("\n 按回车键返回主菜单...")
        elif choice == "0":
            break


def main():
    parser = argparse.ArgumentParser(description="Xidian Steam Dual-Stack & Triple-Stack Optimizer v2.0")
    parser.add_argument("--diagnose", action="store_true", help="Run full diagnosis only")
    parser.add_argument("--apply-dualstack", action="store_true", help="Apply Wired IPv6 + Wi-Fi IPv4 Dual-Stack mode (daemonless)")
    parser.add_argument("--apply-triplestack", action="store_true", help="Apply Wired IPv6 + Wired IPv4 (DPI bypass) + Wi-Fi IPv4 3-Way mode")
    parser.add_argument("--apply-wiredds", action="store_true", help="Apply Single-Cable Wired IPv6 + Wired IPv4 (DPI bypass) Dual-Stack mode")
    parser.add_argument("--apply-ipv6only", action="store_true", help="Apply Pure IPv6 mode")
    parser.add_argument("--clear", action="store_true", help="Clear all Steam Hosts, proxy daemon, tunnels, and routes")
    parser.add_argument("--speedtest", action="store_true", help="Run speedtest")
    parser.add_argument("--run-proxy-daemon", action="store_true", help="Internal: run Triple-Stack proxy in background")
    parser.add_argument("--run-proxy-foreground", action="store_true", help="Run Triple-Stack proxy with live console speed monitor")
    parser.add_argument("--proxy-mode", default="triplestack", choices=["triplestack", "wiredds"], help="Proxy scheduling mode")
    args = parser.parse_args()

    env = detect_network_env()
    if args.run_proxy_daemon:
        proxy = SteamTripleStackProxy(proxy_mode=args.proxy_mode, env=env, quiet=True)
        proxy.serve_forever()
        return
    if args.run_proxy_foreground:
        stop_triple_proxy_daemon()
        gk_v6, _ = scan_best_nodes(env)
        entries = [(gk_v6, gk_dom, "Steam IPv6 Gatekeeper Keep-Alive") for gk_dom in IPV6_GATEKEEPER_DOMAINS]
        for dom, tip in TRIPLE_PROXY_LISTEN_MAP.items():
            entries.append((tip, dom, f"TripleStack Foreground Monitor ({args.proxy_mode})"))
        ensure_mihomo_steam_tunnels({}, clear_only=True)
        apply_wifi_routes(env, clear_only=True)
        update_hosts_file(entries, clear_only=False)
        save_current_state(args.proxy_mode, entries, [], [], env, triple_proxy_pid=os.getpid())
        proxy = SteamTripleStackProxy(proxy_mode=args.proxy_mode, env=env, quiet=False)
        proxy.serve_forever()
        return

    if args.diagnose:
        print_full_diagnosis(env)
        scan_best_nodes(env)
        if args.speedtest:
            run_dualstack_speedtest(env)
        return
    if args.apply_dualstack:
        print_full_diagnosis(env)
        apply_mode("dualstack", env)
        if args.speedtest:
            run_dualstack_speedtest(env)
        return
    if args.apply_triplestack:
        print_full_diagnosis(env)
        apply_mode("triplestack", env)
        return
    if args.apply_wiredds:
        print_full_diagnosis(env)
        apply_mode("wiredds", env)
        return
    if args.apply_ipv6only:
        apply_mode("ipv6only", env)
        return
    if args.clear:
        stop_triple_proxy_daemon()
        ensure_mihomo_steam_tunnels({}, clear_only=True)
        apply_wifi_routes(env, clear_only=True)
        update_hosts_file([], clear_only=True)
        save_current_state("cleared", [], [], [], env, triple_proxy_pid=None)
        print("[+] Cleared all Steam Hosts, Triple-Stack proxy daemon, Mihomo tunnels, and static routes.")
        return
    if args.speedtest:
        run_dualstack_speedtest(env)
        return

    interactive_menu()


if __name__ == "__main__":
    main()
