# ESP32 KVM over IP — Web Control Edition

基于 ESP32-S3 的无线 IP KVM，通过浏览器远程控制目标机的键盘和鼠标，同时在浏览器内嵌入 uStreamer/mjpg-streamer 视频流查看目标机画面。

> **本项目基于 [KMChris/esp32-kvm-ip](https://github.com/KMChris/esp32-kvm-ip) 修改。**
> 原项目版权归 Krzysztof Mizgała 所有，采用 MIT 许可证。

---

## 与原项目的主要区别

| 项目 | 原项目 (KMChris) | 本项目 |
|------|-----------------|--------|
| 控制端 | Windows PC 运行 server.py，捕获本机键鼠 | 任意设备的**浏览器** |
| 传输链路 | Windows Hook → UDP → ESP32 | 浏览器 → WebSocket → Python 桥接 → UDP → ESP32 |
| 视频 | 无 | 嵌入 uStreamer / mjpg-streamer MJPEG 流 |
| 鼠标模式 | 相对坐标 | 相对坐标（Pointer Lock API，兼容 BIOS） |

**ESP32 固件修改：**
- 修复 WiFi 认证模式（`WPA2_WPA3_PSK` → `WPA2_PSK`，原设置在未启用 WPA3 的 sdkconfig 下导致连接失败）
- 修复断线重连逻辑（从 WiFi 事件回调内 `vTaskDelay` 改为独立 `reconnect_task`，避免阻塞事件循环）

---

## 系统架构

```
X10DAI (目标机)
├── HDMI 输出 ──→ USB 采集棒 ──→ TrueNAS VM
│                               └── uStreamer (MJPEG 推流)
│
└── USB 口 ──→ ESP32-S3 (USB OTG)
               └── 模拟 HID 键盘 + 鼠标
                   └── 接收 UDP 指令注入按键

浏览器 ──WebSocket──→ Ubuntu VM (kvm_bridge/server.py)
                      ├── 转发 UDP 包 ──→ ESP32-S3 :4210
                      └── Serve 前端 HTML + /config.json
```

---

## 硬件需求

- **ESP32-S3**（带原生 USB OTG，如 ESP32-S3-DevKitC-1 N16R8）
- USB 线连接 ESP32-S3 **OTG 口** 到目标机（非 UART 口）
- HDMI 采集棒（如 MS2109）连接目标机 HDMI 到运行 uStreamer 的主机
- ESP32-S3 与后端 VM 在同一局域网

---

## 部署

### Part 1：ESP32 固件

1. 安装 [ESP-IDF v5.x](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/)

2. 配置 WiFi：
   ```
   idf.py menuconfig
   ```
   进入 **WiFi Configuration**，填写 SSID 和密码。

3. 编译烧录：
   ```
   idf.py build flash monitor
   ```
   > 烧录时用 **UART 口**接电脑；运行时 **OTG 口**接目标机。两口可同时插。

### Part 2：Ubuntu VM 后端

```bash
pip3 install websockets

# 复制 tools/kvm_bridge/ 到 VM
cp -r tools/kvm_bridge/ ~/kvm-bridge/
cd ~/kvm-bridge

# 编辑配置
nano config.env
# 填写 ESP_IP、USTREAMER_URL 等

# 启动
python3 server.py
```

详细部署说明见 [`tools/kvm_bridge/README.md`](tools/kvm_bridge/README.md)。

### Part 3：浏览器访问

打开 `http://<VM-IP>:8080`，点击视频区域锁定鼠标即可开始控制。

---

## UDP 协议

固定 **16 字节**，little-endian，与原项目完全兼容：

```
Offset  Size  Field
0       2     magic    = 0xCAFE
2       4     sequence (uint32, 单调递增)
6       1     type     (0x01=鼠标 0x02=键盘 0x03=Consumer)
7       1     reserved
8       8     payload  (见 main/protocol.h)
```

---

## 项目结构

```
esp32-kvm-ip/
├── main/
│   ├── main.c               # 初始化：NVS、WiFi、TinyUSB、任务创建
│   ├── Kconfig.projbuild    # WiFi SSID/密码配置
│   ├── tusb_config.h        # TinyUSB 配置
│   ├── usb_descriptors.c/h  # USB HID 描述符 + 回调
│   ├── protocol.h           # UDP 包结构 + 事件类型
│   ├── wifi_manager.c/h     # WiFi STA 初始化（已修改）
│   ├── network_task.c/h     # UDP 接收 → xQueue
│   └── hid_task.c/h         # xQueue → USB HID 报告
└── tools/
    └── kvm_bridge/
        ├── server.py        # Python 后端：WebSocket → UDP 桥接
        ├── config.env       # 本地配置（不提交到 git）
        ├── config.env.example
        ├── requirements.txt
        └── web/
            └── index.html   # 单页面 KVM 前端
```

---

## License

MIT — 详见 [LICENSE](LICENSE)
