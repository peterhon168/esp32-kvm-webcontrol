# ESP32 KVM over IP — Web Control Edition

Browser-based wireless IP KVM using ESP32-S3. Control a remote computer's keyboard and mouse from any browser, with embedded uStreamer/mjpg-streamer video streaming.

> **This project is based on [KMChris/esp32-kvm-ip](https://github.com/KMChris/esp32-kvm-ip).**
> Original project copyright (c) Krzysztof Mizgała, MIT licensed.

---

## Key Differences from the Original

| Feature | Original (KMChris) | This Project |
|---------|-------------------|--------------|
| Control Client | Windows PC running server.py, capturing local keyboard/mouse | **Browser** on any device |
| Transport | Windows Hook → UDP → ESP32 | Browser → WebSocket → Python Bridge → UDP → ESP32 |
| Video | None | Embedded uStreamer / mjpg-streamer MJPEG stream |
| Mouse Mode | Relative coordinates | Relative coordinates (Pointer Lock API, BIOS-compatible) |

**ESP32 Firmware Fixes:**
- Fixed WiFi authentication mode (`WPA2_WPA3_PSK` → `WPA2_PSK` — the original setting caused connection failures on sdkconfig without WPA3 enabled)
- Fixed reconnection logic (replaced `vTaskDelay` inside WiFi event callback with a standalone `reconnect_task` to avoid blocking the event loop)

---

## System Architecture

```
X10DAI (Target Machine)
├── HDMI Output ──→ USB Capture Dongle ──→ TrueNAS VM
│                                         └── uStreamer (MJPEG stream)
│
└── USB Port ──→ ESP32-S3 (USB OTG)
                 └── Emulates HID Keyboard + Mouse
                     └── Receives UDP commands and injects keystrokes

Browser ──WebSocket──→ Ubuntu VM (kvm_bridge/server.py)
                        ├── Forwards UDP packets ──→ ESP32-S3 :4210
                        └── Serves frontend HTML + /config.json
```

---

## Hardware Requirements

- **ESP32-S3** with native USB OTG (e.g., ESP32-S3-DevKitC-1 N16R8)
- USB cable connecting ESP32-S3 **OTG port** to the target machine (not the UART port)
- HDMI capture dongle (e.g., MS2109) connecting target machine HDMI to a host running uStreamer
- ESP32-S3 and the backend VM must be on the same local network

---

## Deployment

### Part 1: ESP32 Firmware

1. Install [ESP-IDF v5.x](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/)

2. Configure WiFi:
   ```
   idf.py menuconfig
   ```
   Navigate to **WiFi Configuration** and enter your SSID and password.

3. Build and flash:
   ```
   idf.py build flash monitor
   ```
   > Use the **UART port** for flashing; use the **OTG port** to connect to the target machine at runtime. Both ports can be plugged in simultaneously.

### Part 2: Ubuntu VM Backend

```bash
pip3 install websockets

# Copy tools/kvm_bridge/ to your VM
cp -r tools/kvm_bridge/ ~/kvm-bridge/
cd ~/kvm-bridge

# Edit config
nano config.env
# Fill in ESP_IP, USTREAMER_URL, etc.

# Start
python3 server.py
```

See [`tools/kvm_bridge/README.md`](tools/kvm_bridge/README.md) for detailed deployment instructions.

### Part 3: Browser Access

Open `http://<VM-IP>:8080`, click the video area to lock the mouse pointer, and start controlling the target machine.

---

## UDP Protocol

Fixed **16 bytes**, little-endian, fully compatible with the original project:

```
Offset  Size  Field
0       2     magic    = 0xCAFE
2       4     sequence (uint32, monotonically increasing)
6       1     type     (0x01=Mouse 0x02=Keyboard 0x03=Consumer)
7       1     reserved
8       8     payload  (see main/protocol.h)
```

---

## Project Structure

```
esp32-kvm-ip/
├── main/
│   ├── main.c               # Init: NVS, WiFi, TinyUSB, task creation
│   ├── Kconfig.projbuild    # WiFi SSID/password config
│   ├── tusb_config.h        # TinyUSB configuration
│   ├── usb_descriptors.c/h  # USB HID descriptors + callbacks
│   ├── protocol.h           # UDP packet structure + event types
│   ├── wifi_manager.c/h     # WiFi STA initialization (modified)
│   ├── network_task.c/h     # UDP receive → xQueue
│   └── hid_task.c/h         # xQueue → USB HID reports
└── tools/
    └── kvm_bridge/
        ├── server.py        # Python backend: WebSocket → UDP bridge
        ├── config.env       # Local config (not committed to git)
        ├── config.env.example
        ├── requirements.txt
        └── web/
            └── index.html   # Single-page KVM frontend
```

---

## License

MIT — see [LICENSE](LICENSE)
