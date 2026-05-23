# KVM Bridge — 部署说明

## 目录结构

```
tools/kvm_bridge/
├── server.py          # Python 后端（WebSocket → UDP）
├── config.env         # 配置文件（编辑这个）
├── requirements.txt   # pip 依赖
├── verify_packets.py  # 包格式验证（无需外部依赖）
└── web/
    └── index.html     # 单页面 KVM 前端
```

---

## Part 1：ESP32 固件

### 需要修改的文件

**`main/wifi_manager.c`**（已修改，两处）

1. 认证模式从 `WIFI_AUTH_WPA2_WPA3_PSK` 改为 `WIFI_AUTH_WPA2_PSK`
   — 原因：sdkconfig 未启用 WPA3，导致连接永远失败

2. 断线重连从事件回调内 `vTaskDelay` 改为独立 `reconnect_task`
   — 原因：在 WiFi 事件循环内阻塞会导致后续事件无法处理

**`main/network_task.c`**（无需修改）

原代码已经：
- 绑定 `INADDR_ANY`（接受任意来源 IP）
- 无来源 IP 过滤
- 包格式验证仅检查 magic 和 size，与新架构完全兼容

### 重新烧录

```bash
# Windows，在 ESP-IDF 环境下
idf.py build flash monitor
# OTG 口接 X10DAI USB，UART 口接电脑（两口可同时插）
```

---

## Part 2：Ubuntu VM 部署

### 2.1 安装依赖

```bash
sudo apt update
sudo apt install -y python3 python3-pip
pip3 install websockets
```

### 2.2 复制文件到 VM

将整个 `tools/kvm_bridge/` 目录复制到 VM，例如 `~/kvm-bridge/`：

```bash
scp -r tools/kvm_bridge/ user@<vm-ip>:~/kvm-bridge/
```

### 2.3 编辑配置

```bash
nano ~/kvm-bridge/config.env
```

```ini
ESP_IP=192.168.1.xxx        # ESP32 的 IP（从路由器 DHCP 表查）
ESP_PORT=4210
WS_PORT=8765
HTTP_PORT=8080
USTREAMER_URL=http://192.168.1.yyy:8080/stream   # uStreamer 地址
```

> **uStreamer 流地址格式**
> - uStreamer：`http://<vm-ip>:8080/stream`
> - mjpg-streamer：`http://<vm-ip>:8080/?action=stream`

### 2.4 启动服务

```bash
cd ~/kvm-bridge
python3 server.py
```

输出示例：
```
2026-05-23 [INFO] kvm: ESP32 target : 192.168.1.100:4210
2026-05-23 [INFO] kvm: uStreamer URL: http://192.168.1.200:8080/stream
2026-05-23 [INFO] kvm: HTTP (web UI): http://0.0.0.0:8080
2026-05-23 [INFO] kvm: WebSocket: ws://0.0.0.0:8765
```

### 2.5 设置为系统服务（可选）

```bash
sudo tee /etc/systemd/system/kvm-bridge.service > /dev/null <<EOF
[Unit]
Description=KVM Bridge (WebSocket→UDP)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/kvm-bridge
ExecStart=/usr/bin/python3 server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now kvm-bridge
sudo systemctl status kvm-bridge
```

---

## Part 3：使用浏览器

1. 打开 `http://<vm-ip>:8080`
2. WebSocket 地址和视频流地址会从 `/config.json` 自动填入
3. 点击「**连接**」建立 WebSocket
4. 点击「**加载**」显示 uStreamer 画面
5. 点击视频区域，或点「**🔒 锁定鼠标**」进入指针锁定模式
   - 锁定后：鼠标相对移动直接注入目标机
   - `Alt+L`：切换锁定/解锁
   - `ESC`：解锁（浏览器原生行为）

---

## 数据流

```
浏览器
  │  mousemove/keydown → JSON over WebSocket
  ▼
Ubuntu VM :8765 (server.py)
  │  JSON → 16-byte UDP packet (protocol.h 格式)
  ▼
ESP32-S3 :4210 (network_task.c)
  │  UDP → hid_event_queue → hid_task.c
  ▼
USB OTG → X10DAI (HID 键盘+鼠标)
```

---

## 故障排查

| 现象 | 检查点 |
|------|--------|
| WiFi 连不上 | 确认 SSID/密码正确；OTG 口接目标机，UART 口接电脑看日志 |
| 浏览器连不上 WS | VM 防火墙是否放行 8765/8080；`ss -tlnp` 确认端口在监听 |
| 键鼠无响应 | `idf.py monitor` 看 ESP32 是否收到 UDP；确认 ESP32 IP 填对 |
| 视频不显示 | uStreamer 是否在运行；浏览器控制台是否有 CORS 错误 |
| BIOS 鼠标不动 | 正常，BIOS 通常只支持相对坐标，已使用相对模式 |
