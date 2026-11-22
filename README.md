1: # 西电校园网多链路聚合与 Steam / XDM / 暴雪战网加速工具箱 (`Xidian_Network_Tools` v2.2)
2: 
3: 本目录收录了专为**西安电子科技大学（Xidian University）**校园网定制的**双网卡（有线 PPPoE + 无线 stu-xdwlan）多通道叠加加速与 DPI 绕过工具集**。目前已全面升级至 **v2.1**，同时支持：
4: 1. **Steam 双端免驻留加速模式 (`dualstack` v1.2 — 日常推荐默认)**：纯 `hosts` + Mihomo 本地回环无线隧道，无 Python 后台进程，实测稳定 **`186.5 ~ 196.11 Mbps`（`23.3 ~ 24.94 MB/s`）**。
5: 2. **Steam 三端超叠加 + 有线 IPv4 DPI 绕过模式 (`triplestack` v2.0)**：本地 `127.0.0.31~37:80` 透明反向代理按连接 **4 : 3 : 3** 轮询分发至 **有线 IPv6 (40%) + 有线 IPv4 [UA伪装绕过DPI] (30%) + 无线 IPv4 (30%)**，彻底解决西电有线网对 Steam 的 0 字节丢包黑洞。
6: 3. **Steam 单网线双栈叠加 + DPI 绕过模式 (`wiredds` v2.0)**：在**未连接无线 Wi-Fi（仅插一根有线网线）**的场景下，自动按 **5 : 5** 叠加 **有线 IPv6 (50%) + 有线 IPv4 [DPI绕过] (50%)**，单根网线即可突破百兆限制跑出 **`20 ~ 21.5 MB/s`** 的双倍速度。
7: 4. **XDM (Xtreme Download Manager) 三通道本地代理 (`Xidian_MultiNet_Proxy.py` v1.2)**：为通用大文件下载提供 `127.0.0.1:10880` 本地 HTTP/SOCKS5 三端聚合代理（`22 ~ 26 MB/s`），支持 **`IP_UNICAST_IF (31)` 内核级网卡强绑**与 **Windows 开机无感静默自启（`pythonw.exe` 完全无黑框）**。
8: 
9: ---
10: 
11: ## 📁 一、 工具箱核心文件清单
12: 
13: | 文件名 | 功能定位与说明 |
14: | :--- | :--- |
15: | **`Start_Steam_DualStack_Optimizer.bat`** | **【Steam 主入口】Steam 双栈/三端超叠加全能控制台 (v2.0)**：双击自动提权，提供 6 大功能菜单（全面体检、双端免驻留模式、三端超叠加模式、单网线双栈模式、纯有线 IPv6 省流模式、一键彻底清理）。 |
16: | **`Start_Steam_TripleStack_Proxy.bat`** | **Steam 三端超叠加 & 实时速率看板快捷启动器 (v2.0)**：支持一键后台静默开启三端超叠加、启动**前台实时三通道速率监控看板**（实时显示 `有线IPv6 / 有线IPv4(DPI绕过) / 无线IPv4` 网速）、或切回双端免驻留模式。 |
17: | **`Steam_DualStack_Optimizer.py`** | **Steam 加速核心引擎脚本 (v2.0)**：内置全链路诊断、有线 IPv4 DPI 黑洞实测、CDN 节点并发优选、Mihomo 无线回环隧道注入（`127.0.0.21~25`）、以及本地三端透明反向代理引擎（`127.0.0.31~37:80`）。 |
18: | **`steam_optimizer_state.json`** | **Steam 状态追踪记录文件**：记录当前所处模式（`dualstack` / `triplestack` / `wiredds` / `ipv6only` / `cleared`）、后台反代进程 `PID`、已注入的 `hosts` 条目、Mihomo 隧道与静态路由，确保每次切换或清理**100% 幂等无残留**。 |
19: | **`Start_XDM_MultiNet_Proxy.bat`** | **【XDM 主入口】XDM 三通道下载加速与开机自启管理器 (v1.2)**：提供 7 项交互菜单（后台静默启动、前台实时监控看板、模式切换、一键开启/关闭 Windows 开机无感静默自启、停止后台代理）。 |
20: | **`Xidian_MultiNet_Proxy.py`** | **XDM 多网卡按连接分流代理源码 (v1.2)**：在 `127.0.0.1:10880` 提供 HTTP/SOCKS5 代理，内置 `IP_UNICAST_IF (31)` 内核级网卡索引绑定、`CREATE_NO_WINDOW` 全程无弹窗探测与注册表 `Run` 开机静默自启管理。 |
21: | **`xdm_proxy_state.json`** | **XDM 代理运行状态记录文件**：记录当前后台 `pythonw.exe` 守护进程 `PID`、监听地址、开机自启开关状态及三通道网卡快照。 |
22: | **`Fix_DualCampusNet_And_IPv6.bat`** | **双校园网底层路由与 IPv6 单边修复工具**：当有线 PPPoE 重拨或无线重连导致双网卡跃点数冲突、IPv6 默认路由丢失时一键修复。 |
23: | **`西电双校园网单边修复与IPv6诊断全记录.md`** | **底层网络拓扑与排障技术档案**：记录西电有线 `CMCC_PPPOE` 与无线 `stu-xdwlan` 的路由表、接口跃点数及 IPv6 诊断细节。 |
24: 
25: ---
26: 
27: ## ⚡ 二、 XDM 三通道聚合代理与「开机无感静默自启」指南 (`v1.2`)
28: 
29: ### 1. 开机无感静默自启状态（当前已默认开启）
30: * **注册表自启项**：`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\XidianMultiNetProxy`
31: * **自启执行命令**：
32:   ```text
33:   "C:\Users\UserX\AppData\Local\Programs\Python\Python313\pythonw.exe" "D:\newproject\mcp-workspace\McpWorkbench-v0.6\Data\default\workspace\Xidian_Network_Tools\Xidian_MultiNet_Proxy.py" --port 10880 --mode all --daemon
34:   ```
35: * **无感静默设计亮点**：
36:   1. **全程零黑框**：采用 `pythonw.exe` 配合 `--daemon` 守护模式运行，且内部定时调用 PowerShell 探测网卡 IP 时强制附加 `CREATE_NO_WINDOW (0x08000000)` 标志，开机与日常运行期间**绝对不会弹出或闪烁任何命令行黑框**。
37:   2. **内核级网卡强绑 (`IP_UNICAST_IF = 31`)**：重启电脑后无需等待或手动注入静态路由，直接通过 Windows 内核套接字选项将分片连接绑定至有线网卡（`IF=72`）与无线网卡（`IF=16`）。
38:   3. **开机拨号自适应轮询**：刚开机若校园网 PPPoE 或 Wi-Fi 尚未完成认证，后台进程会每 10 秒静默探测一次网卡状态，一旦拨号成功立即自动纳入三端分流池。
39: 
40: ### 2. 日常管理方式（图形菜单 & 命令行）
41: 双击 **`Start_XDM_MultiNet_Proxy.bat`** 即可看到当前后台运行状态、开机自启状态及三通道 IP，并可通过菜单操作：
42: * **`[1]` 后台静默开启/重启 三通道全开聚合**（无黑框后台常驻，`127.0.0.1:10880`）
43: * **`[2]` 前台启动三通道实时速率监控看板**（实时查看 `有线v4 | 有线v6 | 无线v4` 分流速率）
44: * **`[3]` 后台开启 双网卡纯 IPv4 聚合模式**（`有线IPv4 60% + 无线IPv4 40%`）
45: * **`[4]` 后台开启 单网线双栈聚合模式**（`有线IPv4 50% + 有线IPv6 50%`）
46: * **`[5]` 开启 Windows 开机无感静默自启**（写入注册表 `Run` 并立即在后台静默启动）
47: * **`[6]` 关闭 Windows 开机自启**（从注册表 `Run` 移除）
48: * **`[7]` 停止正在运行的后台代理进程**
49: 
50: 常用命令行参数：
51: ```powershell
52: # 查看当前 XDM 代理后台运行 PID、三通道网卡状态与开机自启状态
53: python Xidian_MultiNet_Proxy.py --status
54: 
55: # 开启开机无感静默自启并立即在后台启动 (无黑框)
56: python Xidian_MultiNet_Proxy.py --enable-autostart --mode all
57: 
58: # 关闭开机自启
59: python Xidian_MultiNet_Proxy.py --disable-autostart
60: 
61: # 仅在后台静默启动/重启代理 (不改注册表)
62: python Xidian_MultiNet_Proxy.py --start-bg --mode all
63: 
64: # 停止后台代理进程
65: python Xidian_MultiNet_Proxy.py --stop
66: ```
67: 
68: ---
69: 
70: ## 🚀 三、 Steam 加速日常使用指南（4 种模式随心切换）
71: 
72: ### 方法 A：通过图形菜单交互使用（最推荐）
73: 直接双击运行 **`Start_Steam_DualStack_Optimizer.bat`**（或 **`Start_Steam_TripleStack_Proxy.bat`**）：
74: 
75: 1. **选项 `[1]` 全面体检**：
76:    自动检测当前有线 IPv4 (`10.192.x.x`)、有线 IPv6 (`2001:da8:400f::/48`)、无线 IPv4 (`10.175.x.x`) 连接状态，扫描 `D:\steam\logs` 日志中的 IPv6 门禁状态与历史峰值，并实测各 CDN 节点响应延迟。
77: 2. **选项 `[2]` 开启【有线 IPv6 + 无线 IPv4 双端免驻留模式 v1.2】（日常最稳妥推荐，当前激活）**：
78:    * **特点**：无任何后台 Python 驻留进程，完全依靠系统 `hosts` + Clash Verge (`verge-mihomo`) 的 `127.0.0.21~25` 无线网卡回环隧道，有线网口专心跑 IPv6、无线网卡专心跑 IPv4，两者物理隔离互不抢占。
79:    * **分配**：`dl.steam.clngaa.com` + `yif.gdtstream.com` 走**有线教育网 IPv6**；`st.dl.eccdnx.com` 等 5 个域名走**无线 WLAN IPv4**。
80:    * **实测速度**：**`23.3 ~ 24.94 MB/s`（`186.5 ~ 196.11 Mbps`）**。
81: 3. **选项 `[3]` 开启【三端超叠加 + 有线 IPv4 DPI 绕过模式 v2.0】**：
82:    * **特点**：自动在后台静默启动轻量级透明反代（监听 `127.0.0.31 ~ 127.0.0.37:80`），采用与 XDM 相同的**按 TCP 连接 10 槽位加权轮询 (`4:3:3`)**。
83:    * **分配**：每个 Steam CDN 域名的并发连接均自动按 **40% 有线 IPv6 + 30% 有线 IPv4（自动将 `User-Agent` 伪装为 `Mozilla/5.0` 绕过校园网 DPI）+ 30% 无线 IPv4** 动态拆分，且通过 Windows 内核 `IP_UNICAST_IF (31)` 套接字选项精准锁死物理网卡出口。
84: 4. **选项 `[4]` 开启【单网线双栈叠加 + DPI 绕过模式 v2.0】**：
85:    * **适用场景**：**未连接无线 Wi-Fi（仅插一根宿舍有线网线）**。
86:    * **特点**：后台反代自动按 **50% 有线 IPv6 + 50% 有线 IPv4（DPI 绕过）** 轮询分流，单根网线即可从原本的 `11.5 MB/s` 翻倍至 **`20 ~ 21.5 MB/s`**！
87: 5. **选项 `[5]` 开启【纯有线 IPv6 教育网省流加速模式】**：
88:    * **适用场景**：不想启动任何后台进程、且未连无线 Wi-Fi，纯靠教育网 IPv6 稳定跑满单百兆（`11.5 MB/s`），零校园网 IPv4 流量消耗。
89: 6. **选项 `[6]` 一键关闭并彻底清理（恢复默认）**：
90:    * 自动终止后台驻留的三端反代进程、移除 `hosts` 中的 Steam 加速块、清理 Mihomo `127.0.0.21~25` 隧道及静态路由，完全恢复系统初始状态。
91: 
92: ### 方法 B：命令行一键切换参数
93: ```powershell
94: # 1. 开启【双端免驻留模式 v1.2】(有线 IPv6 + 无线 IPv4 Mihomo 隧道，日常推荐)
95: python Steam_DualStack_Optimizer.py --apply-dualstack
96: 
97: # 2. 开启【三端超叠加 + 有线 IPv4 DPI 绕过模式 v2.0】(后台静默运行)
98: python Steam_DualStack_Optimizer.py --apply-triplestack
99: 
100: # 3. 开启【三端超叠加前台实时速率监控台】(实时查看 W_V6 / W_V4 / L_V4 分流网速)
101: python Steam_DualStack_Optimizer.py --run-proxy-foreground --proxy-mode triplestack
102: 
103: # 4. 开启【单网线双栈叠加 + DPI 绕过模式 v2.0】(不连无线 Wi-Fi 时单网线双倍提速)
104: python Steam_DualStack_Optimizer.py --apply-wiredds
105: 
106: # 5. 开启【纯有线 IPv6 省流模式】
107: python Steam_DualStack_Optimizer.py --apply-ipv6only
108: 
109: # 6. 一键彻底关闭并清理所有注入配置与后台进程
110: python Steam_DualStack_Optimizer.py --clear
111: ```
112: 
113: ---
114: 
115: ## 🔄 四、 电脑重启后的自启行为与 Clash Verge 状态说明
116: 
117: 1. **XDM 加速（全自动免干预）**：
118:    * 已配置 Windows 注册表 `Run` 开机无感静默自启（`pythonw.exe` 后台守护），**电脑重启后无需点开任何脚本**，直接打开 XDM 即可享受三通道满速下载。
119: 2. **Steam 加速（在默认的 `dualstack` 双端免驻留模式下）**：
120:    * **`hosts` 规则与 Clash Verge 全局扩展脚本（`Script.js`）均已永久落盘保存**，重启电脑不会丢失。
121:    * **重启电脑后无需重新运行我们的 Python 脚本**，只需确保 **打开了 `Clash Verge`**（让 `verge-mihomo` 内核监听 `127.0.0.21~25` 无线网卡回环隧道），Steam 即可自动跑满有线 IPv6 + 无线 IPv4 双通道！
122: 3. **关于 Clash Verge 可视化窗口找回与防配置冲刷机制**：
123:    * **为什么有时后台有代理但看不到 Clash Verge 窗口？**
124:      Clash Verge 采用 **前端界面 (`clash-verge.exe`) + 后台内核 (`verge-mihomo.exe`)** 分离架构。如果主界面进程意外退出而 `verge-mihomo.exe` 仍作为孤儿进程留在后台，虽然代理端口（`7897` 及 `127.0.0.21~25`）仍在工作，但桌面和托盘将看不到可视化窗口。此时只需重新启动 `D:\clash_verge\clash-verge.exe`（若孤儿内核占用了管道，可先结束 `verge-mihomo.exe` 再打开 `clash-verge.exe`）即可恢复窗口。
125:    * **订阅更新防冲刷保护**：
126:      我们已将 `📶 无线校园网直连(WLAN)` 物理网卡节点、`🎮 暴雪战网与守望先锋` 策略组以及 Steam `127.0.0.21~25` 无线隧道完整写入 Clash Verge 的全局预处理脚本（`profiles\Script.js` 及各订阅关联的 `.js` 脚本）。无论何时打开 Clash Verge 主界面、切换配置或更新机场订阅，这些分流隧道都会被**100% 自动注入保留**，绝不会被订阅更新覆盖。
127: 
128: ---
129: 
130: ## 🔬 五、 技术专题：Steam 三端叠加 vs. XDM 三端叠加核心区别
131: 
132: | 对比维度 | XDM 三端叠加 (`Xidian_MultiNet_Proxy.py` v1.2) | Steam 双端免驻留模式 (`v1.2 dualstack`) | Steam 三端超叠加模式 (`v2.0 triplestack`) |
133: | :--- | :--- | :--- | :--- |
134: | **客户端接入方式** | **显式 HTTP/SOCKS5 代理** (`127.0.0.1:10880`)，XDM 原生支持配置代理服务器 | **纯 `hosts` + Mihomo 无线隧道 (`127.0.0.21~25`)**，无后台 Python 进程 | **`hosts` 劫持 + 本地透明反代 (`127.0.0.31~37:80`)**，解决 Steam 不支持代理的问题 |
135: | **文件切分方式** | **单 URL `Range: bytes=` 切片**：1 个文件拆成 8~16 个字节区间长连接 | **多 CDN 域名 `1 MB` 加密 Chunk**：向不同 CDN 域名并发拉取 1MB 块 | **多 CDN 域名 `1 MB` 加密 Chunk**：单域名内部再次按连接拆分到三端 |
136: | **通道调度粒度** | **按 TCP 连接轮询 (`4:3:3`)** | **按 CDN 域名静态绑定 (`Per-Domain`)**：`clngaa` 走有线 IPv6、`eccdnx` 走无线 IPv4 | **按 TCP 连接轮询 (`4:3:3` / 单网线 `5:5`)**：任意域名的并发连接均动态分流至三端 |
137: | **有线 IPv4 (`10.192.x.x`) DPI 处理** | **原样透传即可通过**：XDM 请求为 HTTPS 加密或标准浏览器 `Mozilla/5.0` UA | **直接规避不用**：有线网口专跑 IPv6，无线网口专跑 IPv4，零物理端口带宽争抢 | **流式重写 UA 彻底绕过 DPI**：在 `W_V4` 通道自动将 `Valve/Steam HTTP Client 1.0` 改写为 `Mozilla/5.0` |
138: | **网卡绑定与自启** | Windows 内核 **`IP_UNICAST_IF (31)`** + 注册表 `pythonw.exe` 开机静默自启 | Mihomo `interface-name: WLAN` + `Script.js` 持久化 | Windows 内核 **`IP_UNICAST_IF (31)`** 强绑物理网卡索引 (`IF=72` / `IF=16`) |
139: 
140: ---
141: 
142: ## 🛠️ 六、 失效时标准诊断与恢复流程（SOP）
143: 
144: 当您遇到 **Steam 下载掉回 `11~12 MB/s`（单链路）、下载速度为 `0 KB/s`、或校园网断线重连后加速失效** 时，请按以下流程排查：
145: 
146: 1. **检查 XDM 代理状态**：
147:    双击 `Start_XDM_MultiNet_Proxy.bat`（或运行 `python Xidian_MultiNet_Proxy.py --status`），确认 `[后台进程状态]` 为 `🟢 运行中`。若异常，按回车选 `[1]` 即可一键重启后台守护进程。
148: 2. **检查 Steam 双栈/三端状态**：
149:    双击 `Start_Steam_DualStack_Optimizer.bat` 选择 **`[1] 全面体检`**：
150:    * 若缺少某条校园网 IP，先重连校园网或运行 **`Fix_DualCampusNet_And_IPv6.bat`**；
151:    * 若提示 `Steam 启动时 ipv6check 自检超时`，重新运行菜单 **`[2] 双端免驻留`** 后**完全退出并重启一次 Steam**；
152:    * 若刚重启电脑后未打开 Clash Verge，打开 Clash Verge 后在 Steam 下载页点击 **【暂停】$\rightarrow$【继续下载】** 即可恢复满速。

---

## 🎮 七、 暴雪战网 / 炉石传说 / 守望先锋 无线网卡 CIDR 网段路由分流与一键还原 (`v1.4`)

针对西电有线校园网（`CMCC_PPPOE`）不仅污染战网 CDN 与登录网关 (`cn.actual.battlenet.com.cn:1119`)，而且在 TCP 层**100% 封锁暴雪国服/网易雷火/阿里云杭州动态匹配对局服务器（`:3724`，导致《炉石传说》《守望先锋》能登录大厅但点击匹配即提示“离线超时”）**的问题，提供 **`Start_BattleNet_WLAN_Switch.bat` / `BattleNet_WLAN_Accelerator.py` (`v1.4`)** 网段级无线路由分流与一键还原控制器：

### 1. 核心架构与解决问题 (`v1.4`)
1. **战网与炉石/守望对局集群 CIDR 网段级无线静态路由 (`Metric=5, IF=WLAN`)**：
   * 游戏进入匹配（`Network.GotoGameServe`）时，战网服务器会直接下发阿里云华东1（杭州）/网易雷火机房的**纯数字 IPv4 + `:3724` 端口**（如 `47.97.166.186:3724`、`47.97.160.102:3724`、`47.98.141.122:3724`、`116.62.23.102:3724`），不经过域名解析与 `hosts`。
   * `v1.4` 将暴雪国服/网易雷火/阿里云杭州对局池的 **16 个核心 CIDR 网段**（`47.96.0.0/14`、`47.110.0.0/15`、`47.114.0.0/15`、`116.62.0.0/16`、`118.31.0.0/16`、`120.26.0.0/15`、`120.55.0.0/16`、`121.40.0.0/14`、`121.196.0.0/14`、`59.111.0.0/16`、`42.186.0.0/16`、`60.188.233.0/24`、`8.149.233.0/24`、`1.95.233.0/24`、`113.137.43.0/24`、`203.2.166.0/24`）精准注入 Windows 内核路由表并指向无线校园网网关（`WLAN 10.175.255.254`）。
2. **默认保持全局 TUN 关闭，100% 保护有线拨号 (`CMCC_PPPOE`) 与信大锐捷 (`XD-NetKeeper.exe`)**：
   * 系统默认路由 (`0.0.0.0/0`) 始终保留在有线宽带 `CMCC_PPPOE` 上，绝不注入 `0.0.0.0/1` 全局劫持路由，信大锐捷在线心跳与日常有线流量完全不受干扰。
3. **炉石日志自动学习 + 实时对局 IP 动态路由守护 (`--watch-matchmaking`)**：
   * 自动扫描 `G:\Hearthstone\Logs\*\GameNetLogger.log` 中的 `GotoGameServe()` 对局 IP；若未来匹配分配到上述 16 个 CIDR 网段之外的新服务器 IP，自动计算并追加其 `/24` 网段路由至无线网卡，同时记录到 `battlenet_wlan_state.json`。
4. **批处理脚本一键完整还原 (`Start_BattleNet_WLAN_Switch.bat` 选项 `[2]` / `--restore` / `Restore_BattleNet_WLAN_Routes.bat`)**：
   * 采用 **Python 状态库清理 + 批处理原生 `route delete <net> mask <mask>` 循环兜底**双重机制，一键删除全部 16 条内置 CIDR 网段路由、日志动态学习的 `/24` 网段路由、`/32` 单点路由及系统 `hosts` 战网锚点块，将 Clash 策略组切回默认有线直连，并核验系统路由表零残留。
5. **修复 `cn.version.battlenet.com.cn:443` TLS 证书报错 (`Schannel:36884`)**：
   * 剔除证书域名不匹配的 `59.111.19.33`，锁定通过 `TLS OK (CN=cn.version.battlenet.com.cn)` 校验的真实节点 (`8.149.233.11` / `47.114.126.40`)。

### 2. 日常使用方法（批处理菜单 & 命令行）
双击 **`Start_BattleNet_WLAN_Switch.bat`**（自动请求管理员权限）即可通过菜单操作：
* **`[1]` 一键开启【战网 + 炉石传说 + 守望先锋 无线 CIDR 网段路由分流加速】**
* **`[2]` 一键还原【彻底清除全部已注入的 CIDR 网段路由、单点路由与 Hosts 映射，恢复纯有线默认状态】**
* **`[3]` 状态诊断【核验系统路由表生效网段数，并并发实测战网登录 (`:1119`)、版本校验 (`:443 TLS`) 与炉石对局服 (`:3724`) 连通性】**
* **`[4]` 动态守护【前台启动炉石/守望匹配对局 IP 实时日志监控，新网段自动注入无线路由】**

此外还提供了两个独立的一键批处理快捷脚本（双击即可执行）：
* **`Apply_BattleNet_WLAN_Routes.bat`**：一键提权向系统路由表注入全部 16 条战网/炉石对局集群 CIDR 无线网段路由。
* **`Restore_BattleNet_WLAN_Routes.bat`**：一键提权彻底清除全部已注入的 CIDR 网段路由、单点路由与 `hosts` 规则。

常用命令行参数：
```powershell
# 一键开启战网与炉石/守望对局集群无线 CIDR 网段路由分流
Start_BattleNet_WLAN_Switch.bat --enable-wlan

# 一键还原：彻底删除全部已注入的 CIDR 网段路由、单点路由与 Hosts 映射
Start_BattleNet_WLAN_Switch.bat --restore

# 查看当前生效的 CIDR 网段路由表并实测登录服 (:1119) 与炉石对局服 (:3724) 连通性
python -X utf8 BattleNet_WLAN_Accelerator.py --status

# 启动炉石/守望匹配对局 IP 实时动态路由守护
python -X utf8 BattleNet_WLAN_Accelerator.py --watch-matchmaking
```
