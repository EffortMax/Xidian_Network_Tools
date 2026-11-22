#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
================================================================================
西电双校园网 / 三通道智能聚合本地代理 (Xidian Multi-Channel Load-Balancing Proxy v1.2)
适配工具: XDM (Xtreme Download Manager 9.x / 8.x)、IDM、Motrix、Aria2、浏览器、curl 等
监听地址: 127.0.0.1:10880 (单端口同时自动识别 HTTP/HTTPS CONNECT 代理 与 SOCKS5 代理)

[v1.2 升级特性]:
  1. 内核级网卡强绑 (IP_UNICAST_IF = 31):
     - 自动获取有线 CMCC_PPPOE 与无线 WLAN 的 InterfaceIndex，通过 winsock IP_UNICAST_IF
       直接将每个分片连接钉死在对应物理网卡上，重启电脑后无需注入静态路由即可 100% 精准分流。
  2. 完全无黑框静默后台守护 (--daemon / --start-bg) 与开机无感自启 (--enable-autostart):
     - 子进程探测全程携带 CREATE_NO_WINDOW (0x08000000)，后台运行时绝不闪烁 PowerShell 黑框；
     - 支持一键写入/移除注册表 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 开机静默自启。
================================================================================
"""

import argparse
import datetime
import json
import os
import select
import socket
import struct
import subprocess
import sys
import threading
import time

BUFFER_SIZE = 131072  # 128 KiB 高吞吐缓冲区
IP_UNICAST_IF = 31    # Windows winsock IP_UNICAST_IF option
CREATE_NO_WINDOW = 0x08000000

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "xdm_proxy_state.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "xdm_multinet_proxy.log")
RUN_REG_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
RUN_REG_VALUE_NAME = "XidianMultiNetProxy"


def log_msg(msg: str, daemon: bool = False):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    if not daemon and sys.stdout is not None:
        try:
            print(msg)
        except Exception:
            pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="ignore") as f:
            f.write(line + "\n")
    except Exception:
        pass


class ChannelState:
    def __init__(self, mode="all", daemon=False):
        self.mode = mode  # "all" | "dual-v4" | "wired-dualstack"
        self.daemon = daemon
        self.wired_v4 = None
        self.wired_v4_idx = None
        self.wlan_v4 = None
        self.wlan_v4_idx = None
        self.wired_v6_avail = False
        self.wired_v6 = None
        self.lock = threading.Lock()
        self.rr_counter = 0
        # 实时流量统计 (bytes)
        self.bytes_wired_v4 = 0
        self.bytes_wired_v6 = 0
        self.bytes_wlan_v4 = 0
        self.active_conns = 0
        # DNS 与 IPv6 可达性黑名单缓存
        self.dns_cache = {}
        self.v6_fail_hosts = {}  # host -> timestamp

    def detect_interfaces(self):
        """通过无窗口 PowerShell 自动探测当前有线 PPPoE 与无线 WLAN 的动态 IP 及 InterfaceIndex"""
        ps_cmd = (
            "Get-NetIPAddress | Where-Object {$_.PrefixOrigin -ne 'WellKnown'} | "
            "Select-Object InterfaceAlias,InterfaceIndex,AddressFamily,IPAddress | ConvertTo-Json -Compress"
        )
        wired_v4 = None
        wired_v4_idx = None
        wlan_v4 = None
        wlan_v4_idx = None
        wired_v6 = False
        wired_v6_ip = None
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
            ).strip()
            if out:
                items = json.loads(out)
                if isinstance(items, dict):
                    items = [items]
                for it in items:
                    alias = str(it.get("InterfaceAlias", ""))
                    ip = str(it.get("IPAddress", ""))
                    fam = it.get("AddressFamily")
                    if_idx = it.get("InterfaceIndex")
                    if ("PPPOE" in alias.upper() or ip.startswith("10.192.")) and fam == 2:
                        wired_v4 = ip
                        wired_v4_idx = if_idx
                    elif ("WLAN" in alias.upper() or "WI-FI" in alias.upper() or ip.startswith("10.175.")) and fam == 2:
                        if not ip.startswith("169.254."):
                            wlan_v4 = ip
                            wlan_v4_idx = if_idx
                    elif ("PPPOE" in alias.upper() or ip.startswith("2001:da8:")) and fam == 23:
                        if not ip.lower().startswith("fe80"):
                            wired_v6 = True
                            wired_v6_ip = ip
        except Exception:
            pass

        with self.lock:
            self.wired_v4 = wired_v4
            self.wired_v4_idx = wired_v4_idx
            self.wlan_v4 = wlan_v4
            self.wlan_v4_idx = wlan_v4_idx
            self.wired_v6_avail = wired_v6
            self.wired_v6 = wired_v6_ip

    def resolve_host(self, host, port):
        now = time.time()
        key = (host, port)
        with self.lock:
            cached = self.dns_cache.get(key)
            if cached and now - cached[0] < 60.0:
                return cached[1], cached[2]

        v4_addrs = []
        v6_addrs = []
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for fam, _, _, _, sockaddr in infos:
                if fam == socket.AF_INET and sockaddr not in v4_addrs:
                    v4_addrs.append(sockaddr)
                elif fam == socket.AF_INET6 and sockaddr not in v6_addrs:
                    v6_addrs.append(sockaddr)
        except Exception:
            pass

        with self.lock:
            self.dns_cache[key] = (now, v4_addrs, v6_addrs)
        return v4_addrs, v6_addrs

    def pick_channel_sequence(self, host, has_v4, has_v6):
        """
        根据当前模式、目标站点是否支持 IPv6 以及 10 槽位加权轮询返回优先尝试的通道序列:
        通道标识: 'W_V6' (有线IPv6), 'W_V4' (有线IPv4), 'L_V4' (无线IPv4)
        """
        with self.lock:
            idx = self.rr_counter % 10
            self.rr_counter += 1
            w4 = self.wired_v4
            l4 = self.wlan_v4
            v6_ok = self.wired_v6_avail and has_v6 and (time.time() - self.v6_fail_hosts.get(host, 0) > 120)

        if self.mode == "wired-dualstack":
            if v6_ok and has_v4:
                return ["W_V6", "W_V4"] if (idx % 2 == 0) else ["W_V4", "W_V6"]
            elif v6_ok:
                return ["W_V6"]
            else:
                return ["W_V4"]

        if self.mode == "dual-v4" or not v6_ok:
            if w4 and l4 and has_v4:
                prefer_wlan = idx in (2, 4, 6, 9)
                return ["L_V4", "W_V4"] if prefer_wlan else ["W_V4", "L_V4"]
            elif w4 and has_v4:
                return ["W_V4"]
            elif l4 and has_v4:
                return ["L_V4"]
            elif v6_ok:
                return ["W_V6"]
            return ["W_V4"]

        # Mode == "all" 且目标同时支持 IPv6 与 IPv4:
        # 10 槽位映射: 0,3,6,8 -> W_V6 (40%); 1,4,7 -> W_V4 (30%); 2,5,9 -> L_V4 (30%)
        if idx in (0, 3, 6, 8):
            return ["W_V6", "W_V4", "L_V4"]
        elif idx in (2, 5, 9) and l4:
            return ["L_V4", "W_V4", "W_V6"]
        else:
            return ["W_V4", "L_V4", "W_V6"]

    def _bind_v4_interface(self, s, bind_ip, if_idx):
        if if_idx:
            try:
                s.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", int(if_idx)))
            except Exception:
                pass
        if bind_ip:
            s.bind((bind_ip, 0))

    def connect_outbound(self, host, port):
        v4_addrs, v6_addrs = self.resolve_host(host, port)
        seq = self.pick_channel_sequence(host, bool(v4_addrs), bool(v6_addrs))

        for ch in seq:
            s = None
            try:
                if ch == "W_V6" and v6_addrs:
                    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    s.settimeout(2.5)
                    s.connect(v6_addrs[0])
                    s.settimeout(30.0)
                    return s, "W_V6"
                elif ch == "W_V4" and v4_addrs:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    s.settimeout(3.0)
                    self._bind_v4_interface(s, self.wired_v4, self.wired_v4_idx)
                    s.connect(v4_addrs[0])
                    s.settimeout(30.0)
                    return s, "W_V4"
                elif ch == "L_V4" and v4_addrs and self.wlan_v4:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    s.settimeout(3.0)
                    self._bind_v4_interface(s, self.wlan_v4, self.wlan_v4_idx)
                    s.connect(v4_addrs[0])
                    s.settimeout(30.0)
                    return s, "L_V4"
            except Exception:
                if ch == "W_V6":
                    with self.lock:
                        self.v6_fail_hosts[host] = time.time()
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass

        s = socket.create_connection((host, port), timeout=5.0)
        s.settimeout(None)
        return s, "W_V4"

    def add_bytes(self, ch, n):
        with self.lock:
            if ch == "W_V6":
                self.bytes_wired_v6 += n
            elif ch == "L_V4":
                self.bytes_wlan_v4 += n
            else:
                self.bytes_wired_v4 += n


def _pump_up(client_sock, remote_sock):
    try:
        while True:
            data = client_sock.recv(65536)
            if not data:
                break
            remote_sock.sendall(data)
    except Exception:
        pass
    finally:
        try:
            remote_sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass


def relay_sockets(client_sock, remote_sock, state, ch):
    with state.lock:
        state.active_conns += 1
    try:
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2097152)
        client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        t_up = threading.Thread(target=_pump_up, args=(client_sock, remote_sock), daemon=True)
        t_up.start()
        while True:
            data = remote_sock.recv(BUFFER_SIZE)
            if not data:
                break
            client_sock.sendall(data)
            state.add_bytes(ch, len(data))
    except Exception:
        pass
    finally:
        with state.lock:
            state.active_conns -= 1
        try:
            client_sock.close()
        except Exception:
            pass
        try:
            remote_sock.close()
        except Exception:
            pass


def handle_socks5(client_sock, first_byte, state):
    hdr = client_sock.recv(1)
    if not hdr:
        return
    nmethods = hdr[0]
    if nmethods > 0:
        client_sock.recv(nmethods)
    client_sock.sendall(b"\x05\x00")
    req = client_sock.recv(4)
    if len(req) < 4 or req[1] != 1:
        client_sock.close()
        return
    atyp = req[3]
    if atyp == 1:
        addr_bytes = client_sock.recv(4)
        host = socket.inet_ntoa(addr_bytes)
    elif atyp == 3:
        dlen = client_sock.recv(1)[0]
        host = client_sock.recv(dlen).decode("ascii", errors="ignore")
    elif atyp == 4:
        addr_bytes = client_sock.recv(16)
        host = socket.inet_ntop(socket.AF_INET6, addr_bytes)
    else:
        client_sock.close()
        return
    port = struct.unpack("!H", client_sock.recv(2))[0]

    remote_sock, ch = state.connect_outbound(host, port)
    client_sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
    relay_sockets(client_sock, remote_sock, state, ch)


def handle_http_proxy(client_sock, first_byte, state):
    buf = first_byte
    while b"\r\n\r\n" not in buf and len(buf) < 65536:
        chunk = client_sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    header_end = buf.find(b"\r\n\r\n")
    if header_end == -1:
        client_sock.close()
        return

    header_text = buf[:header_end].decode("iso-8859-1", errors="ignore")
    body_remainder = buf[header_end + 4:]
    lines = header_text.split("\r\n")
    req_line = lines[0].split(" ")
    if len(req_line) < 3:
        client_sock.close()
        return
    method, target, version = req_line[0], req_line[1], req_line[2]

    if method.upper() == "CONNECT":
        if ":" in target:
            host, port_s = target.rsplit(":", 1)
            port = int(port_s)
        else:
            host, port = target, 443
        host = host.strip("[]")
        remote_sock, ch = state.connect_outbound(host, port)
        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        if body_remainder:
            remote_sock.sendall(body_remainder)
        relay_sockets(client_sock, remote_sock, state, ch)
    else:
        import urllib.parse
        u = urllib.parse.urlsplit(target)
        host = u.hostname
        port = u.port or (443 if u.scheme == "https" else 80)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        if not host:
            client_sock.close()
            return
        remote_sock, ch = state.connect_outbound(host, port)
        new_lines = [f"{method} {path} {version}"]
        for l in lines[1:]:
            if not l.lower().startswith("proxy-"):
                new_lines.append(l)
        out_hdr = ("\r\n".join(new_lines) + "\r\n\r\n").encode("iso-8859-1")
        remote_sock.sendall(out_hdr + body_remainder)
        relay_sockets(client_sock, remote_sock, state, ch)


def handle_client(client_sock, state):
    try:
        client_sock.settimeout(10.0)
        first = client_sock.recv(1)
        if not first:
            client_sock.close()
            return
        client_sock.settimeout(None)
        if first == b"\x05":
            handle_socks5(client_sock, first, state)
        else:
            handle_http_proxy(client_sock, first, state)
    except Exception:
        try:
            client_sock.close()
        except Exception:
            pass


def monitor_loop(state):
    prev_w4 = prev_w6 = prev_l4 = 0
    prev_t = time.perf_counter()
    refresh_counter = 0
    while True:
        time.sleep(1.0)
        now = time.perf_counter()
        dt = now - prev_t
        prev_t = now
        with state.lock:
            cw4, cw6, cl4 = state.bytes_wired_v4, state.bytes_wired_v6, state.bytes_wlan_v4
            conns = state.active_conns
            has_all = bool(state.wired_v4 and state.wlan_v4)
        rw4 = (cw4 - prev_w4) / dt / (1024 * 1024)
        rw6 = (cw6 - prev_w6) / dt / (1024 * 1024)
        rl4 = (cl4 - prev_l4) / dt / (1024 * 1024)
        prev_w4, prev_w6, prev_l4 = cw4, cw6, cl4
        rtot = rw4 + rw6 + rl4
        if not state.daemon and sys.stdout is not None and (conns > 0 or rtot > 0.05):
            mb_tot = rtot * 1.048576
            mbps_tot = rtot * 8.388608
            try:
                sys.stdout.write(
                    f"\r[实时速率] 总计: {rtot:5.2f} MiB/s ({mb_tot:5.2f} MB/s, {mbps_tot:5.1f} Mbps) | "
                    f"有线v4: {rw4:5.2f} | 有线v6: {rw6:5.2f} | 无线v4: {rl4:5.2f} MiB/s | 活跃分片: {conns:2d}   "
                )
                sys.stdout.flush()
            except Exception:
                pass
        refresh_counter += 1
        interval = 45 if has_all else 10
        if refresh_counter >= interval:
            refresh_counter = 0
            state.detect_interfaces()


def save_proxy_state(pid, host, port, mode, state_obj: ChannelState):
    data = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.2",
        "pid": pid,
        "listen": f"{host}:{port}",
        "mode": mode,
        "autostart_enabled": is_autostart_enabled(),
        "channels": {
            "wired_v4": state_obj.wired_v4,
            "wired_v4_idx": state_obj.wired_v4_idx,
            "wired_v6": state_obj.wired_v6,
            "wlan_v4": state_obj.wlan_v4,
            "wlan_v4_idx": state_obj.wlan_v4_idx,
        },
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_pythonw_exe():
    py_dir = os.path.dirname(sys.executable)
    pw = os.path.join(py_dir, "pythonw.exe")
    if os.path.exists(pw):
        return pw
    return sys.executable


def is_autostart_enabled():
    try:
        r = subprocess.run(
            ["reg", "query", RUN_REG_KEY, "/v", RUN_REG_VALUE_NAME],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0 and RUN_REG_VALUE_NAME in (r.stdout or "")
    except Exception:
        return False


def get_autostart_cmd():
    try:
        r = subprocess.run(
            ["reg", "query", RUN_REG_KEY, "/v", RUN_REG_VALUE_NAME],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                if RUN_REG_VALUE_NAME in line and "REG_SZ" in line:
                    return line.split("REG_SZ", 1)[1].strip()
    except Exception:
        pass
    return None


def set_autostart(enable: bool, port: int = 10880, mode: str = "all"):
    if enable:
        pw = get_pythonw_exe()
        script_path = os.path.abspath(__file__)
        cmd_val = f'"{pw}" "{script_path}" --port {port} --mode {mode} --daemon'
        r = subprocess.run(
            ["reg", "add", RUN_REG_KEY, "/v", RUN_REG_VALUE_NAME, "/t", "REG_SZ", "/d", cmd_val, "/f"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            print(f"[+] 已成功配置 XDM 三通道代理开机无感静默自启！")
            print(f"    -> 注册表路径: {RUN_REG_KEY}\\{RUN_REG_VALUE_NAME}")
            print(f"    -> 自启命令行: {cmd_val}")
            return True
        else:
            print(f"[!] 注册表写入失败: {r.stderr or r.stdout}")
            return False
    else:
        r = subprocess.run(
            ["reg", "delete", RUN_REG_KEY, "/v", RUN_REG_VALUE_NAME, "/f"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            print("[+] 已移除 XDM 三通道代理的开机自启项。")
        else:
            print("[*] 当前未配置开机自启项，无需移除。")
        return True


def find_listening_pid(port: int = 10880):
    ps_cmd = (
        f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty OwningProcess -First 1"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        ).strip()
        if out and out.isdigit():
            return int(out)
    except Exception:
        pass
    return None


def stop_existing_proxy(port: int = 10880):
    stopped = []
    pid = find_listening_pid(port)
    if pid and pid != os.getpid():
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        stopped.append(pid)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
            spid = st.get("pid")
            if spid and spid != os.getpid() and spid not in stopped:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(spid)],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                stopped.append(spid)
        except Exception:
            pass
    time.sleep(0.3)
    return stopped


def start_background_daemon(host: str = "127.0.0.1", port: int = 10880, mode: str = "all"):
    stopped = stop_existing_proxy(port)
    if stopped:
        print(f"[*] 已清理旧的代理进程 PID: {stopped}")
    pw = get_pythonw_exe()
    script_path = os.path.abspath(__file__)
    proc = subprocess.Popen(
        [pw, script_path, "--host", host, "--port", str(port), "--mode", mode, "--daemon"],
        cwd=SCRIPT_DIR,
        creationflags=CREATE_NO_WINDOW | 0x00000008,  # DETACHED_PROCESS
        close_fds=True,
    )
    for _ in range(25):
        time.sleep(0.2)
        lpid = find_listening_pid(port)
        if lpid:
            print(f"[+] XDM 多通道聚合代理已在后台静默启动！(PID: {lpid}, 监听: {host}:{port}, 模式: {mode})")
            return lpid
    print(f"[!] 后台进程已拉起 (PID: {proc.pid})，请检查端口 {port} 状态。")
    return proc.pid


def show_status(host: str = "127.0.0.1", port: int = 10880):
    lpid = find_listening_pid(port)
    auto_en = is_autostart_enabled()
    auto_cmd = get_autostart_cmd()
    state = ChannelState(mode="all", daemon=True)
    state.detect_interfaces()
    print("==========================================================================")
    print("  西电 XDM 三通道智能聚合本地代理 v1.2 — 状态诊断面板")
    print("==========================================================================")
    print(f"  [后台进程状态] : {'🟢 运行中 (PID: ' + str(lpid) + f', 监听 {host}:{port})' if lpid else '🔴 未运行'}")
    print(f"  [开机静默自启] : {'🟢 已开启 (pythonw 无黑框模式)' if auto_en else '⚪ 未开启'}")
    if auto_cmd:
        print(f"  [自启注册表项] : {auto_cmd}")
    print("--------------------------------------------------------------------------")
    print(f"  [通道 1 有线 IPv4] : {state.wired_v4 or '未检测到'} (IF={state.wired_v4_idx})")
    print(f"  [通道 2 有线 IPv6] : {state.wired_v6 or ('已就绪' if state.wired_v6_avail else '未检测到')}")
    print(f"  [通道 3 无线 IPv4] : {state.wlan_v4 or '未检测到'} (IF={state.wlan_v4_idx})")
    print("==========================================================================")


def main():
    parser = argparse.ArgumentParser(description="西电三通道/双网卡智能聚合本地代理 v1.2 (适配 XDM / IDM / Motrix)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=10880, help="监听端口 (默认 10880)")
    parser.add_argument(
        "--mode",
        choices=["all", "dual-v4", "wired-dualstack"],
        default="all",
        help="聚合模式: all(有线v4+有线v6+无线v4三通道,默认) | dual-v4(有线v4+无线v4双网卡) | wired-dualstack(单网线IPv4+IPv6)",
    )
    parser.add_argument("--daemon", action="store_true", help="以无窗口后台静默守护进程模式运行")
    parser.add_argument("--start-bg", action="store_true", help="启动/重启后台无黑框静默代理进程并退出")
    parser.add_argument("--stop", action="store_true", help="停止正在运行的后台代理进程")
    parser.add_argument("--enable-autostart", action="store_true", help="开启 Windows 开机无感静默自启并确保后台运行")
    parser.add_argument("--disable-autostart", action="store_true", help="关闭 Windows 开机自启")
    parser.add_argument("--status", action="store_true", help="查看当前代理进程状态与开机自启状态")
    args = parser.parse_args()

    if args.status:
        show_status(args.host, args.port)
        return

    if args.stop:
        stopped = stop_existing_proxy(args.port)
        if stopped:
            print(f"[+] 已停止 XDM 多通道聚合后台代理进程 (PID: {stopped})。")
        else:
            print("[*] 当前没有正在运行的 XDM 代理进程。")
        return

    if args.disable_autostart:
        set_autostart(False)
        return

    if args.enable_autostart:
        set_autostart(True, args.port, args.mode)
        start_background_daemon(args.host, args.port, args.mode)
        return

    if args.start_bg:
        start_background_daemon(args.host, args.port, args.mode)
        return

    existing_pid = find_listening_pid(args.port)
    if existing_pid and existing_pid != os.getpid():
        stop_existing_proxy(args.port)

    state = ChannelState(mode=args.mode, daemon=args.daemon)
    state.detect_interfaces()
    save_proxy_state(os.getpid(), args.host, args.port, args.mode, state)

    if not args.daemon:
        print("==========================================================================")
        print("  西电双校园网 / 三通道智能聚合本地代理 v1.2 (XDM / IDM / Motrix 专用加速器)")
        print("==========================================================================")
        print("[*] 正在探测本机当前有线 PPPoE 与无线 WLAN 通道状态 (内核 IP_UNICAST_IF 强绑)...")
        print(f"    -> ① 有线 CMCC_PPPOE IPv4 : {state.wired_v4 or '未检测到'} (IF={state.wired_v4_idx}, 独立 100Mbps 移动桶)")
        print(f"    -> ② 有线 CMCC_PPPOE IPv6 : {state.wired_v6 or ('已就绪' if state.wired_v6_avail else '未检测到')} (独立 100Mbps 教育网桶)")
        print(f"    -> ③ 无线 stu-xdwlan IPv4 : {state.wlan_v4 or '未检测到'} (IF={state.wlan_v4_idx}, 独立 ~80Mbps 校园网桶)")
        print(f"[*] 当前运行模式: {args.mode} | 开机静默自启: {'已开启' if is_autostart_enabled() else '未开启'}")
        print(f"[*] 本地代理已启动: {args.host}:{args.port} (同时支持 HTTP/HTTPS 代理 与 SOCKS5 代理)")
        print("==========================================================================")
    else:
        log_msg(
            f"XDM MultiNet Proxy v1.2 daemon started (PID={os.getpid()}, listen={args.host}:{args.port}, mode={args.mode}, "
            f"W_V4={state.wired_v4}/IF={state.wired_v4_idx}, W_V6={state.wired_v6}, L_V4={state.wlan_v4}/IF={state.wlan_v4_idx})",
            daemon=True,
        )

    threading.Thread(target=monitor_loop, args=(state,), daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(256)

    try:
        while True:
            client_sock, _ = server.accept()
            threading.Thread(target=handle_client, args=(client_sock, state), daemon=True).start()
    except KeyboardInterrupt:
        if not args.daemon:
            print("\n[*] 代理已停止。")


if __name__ == "__main__":
    main()
