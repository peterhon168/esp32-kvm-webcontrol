#!/usr/bin/env python3
"""
KVM Bridge Server
WebSocket (browser) → UDP (ESP32-S3 HID)

Usage:
    pip install websockets
    python3 server.py

Configuration via environment variables or config.env file:
    ESP_IP          ESP32 IP address          (required)
    ESP_PORT        ESP32 UDP port            (default: 4210)
    WS_PORT         WebSocket listen port     (default: 8765)
    HTTP_PORT       Web UI HTTP port          (default: 8080)
    USTREAMER_URL   uStreamer stream URL      (default: http://localhost:8080/stream)
"""

import asyncio
import json
import logging
import os
import socket
import struct
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import websockets

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("kvm")

# ── Config (env vars, with fallback to config.env file) ───────────
def load_config():
    cfg_file = Path(__file__).parent / "config.env"
    if cfg_file.exists():
        for line in cfg_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

load_config()

ESP_IP        = os.environ.get("ESP_IP", "")
ESP_PORT      = int(os.environ.get("ESP_PORT", "4210"))
WS_PORT       = int(os.environ.get("WS_PORT", "8765"))
HTTP_PORT     = int(os.environ.get("HTTP_PORT", "8080"))
USTREAMER_URL = os.environ.get("USTREAMER_URL", "")

if not ESP_IP:
    raise SystemExit("ERROR: ESP_IP is not set. Create config.env or set the environment variable.")

# ── Protocol constants — must match ESP32 protocol.h ─────────────
#
# Packet layout (16 bytes, little-endian):
#   Offset  Size  Field
#   0       2     magic    = 0xCAFE
#   2       4     sequence (uint32)
#   6       1     type     (0x01=mouse, 0x02=keyboard, 0x03=consumer)
#   7       1     reserved = 0x00
#   8       8     payload  (union, see below)
#
# Mouse payload (8 bytes):
#   8       1     buttons  (uint8,  bit0=L bit1=R bit2=M bit3=Back bit4=Fwd)
#   9       2     dx       (int16)
#   11      2     dy       (int16)
#   13      1     wheel    (int8)
#   14      1     pan      (int8)
#   15      1     _pad     = 0x00
#
# Keyboard payload (8 bytes):
#   8       1     modifiers (uint8)
#   9       1     reserved  = 0x00
#   10      6     keycodes[6] (uint8 each)
#
# Consumer payload (8 bytes):
#   8       2     usage_id (uint16)
#   10      6     _pad     = 0x00

PACKET_MAGIC = 0xCAFE
PACKET_SIZE  = 16
EVENT_MOUSE    = 0x01
EVENT_KEYBOARD = 0x02
EVENT_CONSUMER = 0x03

_seq = 0

def _next_seq() -> int:
    global _seq
    _seq = (_seq + 1) & 0xFFFFFFFF
    return _seq

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def make_mouse_packet(buttons: int, dx: int, dy: int,
                      wheel: int, pan: int) -> bytes:
    # Header: magic(H) seq(I) type(B) reserved(B)  → 8 bytes
    # Payload: buttons(B) dx(h) dy(h) wheel(b) pan(b) pad(B)  → 8 bytes
    # Total: 16 bytes
    pkt = struct.pack(
        "<HIBBBhhbbB",
        PACKET_MAGIC,
        _next_seq(),
        EVENT_MOUSE,
        0,                              # reserved
        _clamp(buttons, 0, 0xFF),
        _clamp(dx,    -32767, 32767),
        _clamp(dy,    -32767, 32767),
        _clamp(wheel,   -127,   127),
        _clamp(pan,     -127,   127),
        0,                              # _pad
    )
    assert len(pkt) == PACKET_SIZE, f"mouse packet size {len(pkt)} != {PACKET_SIZE}"
    return pkt

def make_keyboard_packet(modifiers: int, keycodes: list) -> bytes:
    # Header: magic(H) seq(I) type(B) reserved(B)  → 8 bytes
    # Payload: modifiers(B) reserved(B) keycodes[6](6B)  → 8 bytes
    keys = (list(keycodes) + [0, 0, 0, 0, 0, 0])[:6]
    pkt = struct.pack(
        "<HIBBBBBBBBBB",
        PACKET_MAGIC,
        _next_seq(),
        EVENT_KEYBOARD,
        0,                              # reserved
        _clamp(modifiers, 0, 0xFF),
        0,                              # reserved in payload
        keys[0], keys[1], keys[2],
        keys[3], keys[4], keys[5],
    )
    assert len(pkt) == PACKET_SIZE, f"keyboard packet size {len(pkt)} != {PACKET_SIZE}"
    return pkt

def make_consumer_packet(usage_id: int) -> bytes:
    # Header: magic(H) seq(I) type(B) reserved(B)  → 8 bytes
    # Payload: usage_id(H) pad(6B)  → 8 bytes
    pkt = struct.pack(
        "<HIBBHBBBBBB",
        PACKET_MAGIC,
        _next_seq(),
        EVENT_CONSUMER,
        0,                              # reserved
        _clamp(usage_id, 0, 0xFFFF),
        0, 0, 0, 0, 0, 0,              # _pad[6]
    )
    assert len(pkt) == PACKET_SIZE, f"consumer packet size {len(pkt)} != {PACKET_SIZE}"
    return pkt

# ── UDP sender ────────────────────────────────────────────────────
class UDPSender:
    def __init__(self, ip: str, port: int):
        self._addr = (ip, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        log.info(f"UDP target: {ip}:{port}")

    def send(self, data: bytes) -> None:
        try:
            self._sock.sendto(data, self._addr)
        except OSError as e:
            log.error(f"UDP send failed: {e}")

_udp = UDPSender(ESP_IP, ESP_PORT)

# ── WebSocket handler ─────────────────────────────────────────────
async def ws_handler(websocket):
    peer = websocket.remote_address
    log.info(f"WS connected: {peer}")
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
                t = msg.get("type")

                if t == "mouse":
                    pkt = make_mouse_packet(
                        int(msg.get("buttons", 0)),
                        int(msg.get("dx", 0)),
                        int(msg.get("dy", 0)),
                        int(msg.get("wheel", 0)),
                        int(msg.get("pan", 0)),
                    )
                elif t == "keyboard":
                    pkt = make_keyboard_packet(
                        int(msg.get("modifiers", 0)),
                        [int(k) for k in msg.get("keycodes", [])],
                    )
                elif t == "consumer":
                    pkt = make_consumer_packet(int(msg.get("usage_id", 0)))
                else:
                    log.debug(f"Unknown msg type: {t!r}")
                    continue

                _udp.send(pkt)

            except (json.JSONDecodeError, KeyError, ValueError, AssertionError) as e:
                log.warning(f"Bad message from {peer}: {e} | raw={raw!r:.80}")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        log.info(f"WS disconnected: {peer}")

# ── HTTP server (serves web/ directory) ───────────────────────────
class _Handler(SimpleHTTPRequestHandler):
    _web_dir = str(Path(__file__).parent / "web")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=self._web_dir, **kwargs)

    def log_message(self, fmt, *args):  # silence access log
        pass

    def end_headers(self):
        # Allow MJPEG stream to be embedded (CORS for same-LAN use)
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

def _run_http(port: int) -> None:
    Path(_Handler._web_dir).mkdir(parents=True, exist_ok=True)
    srv = HTTPServer(("0.0.0.0", port), _Handler)
    log.info(f"HTTP (web UI): http://0.0.0.0:{port}")
    srv.serve_forever()

# ── Config endpoint — lets the frontend discover its settings ─────
# Injected into index.html at serve time via a tiny JSON endpoint.
# We patch the HTTP handler to respond to GET /config.json

class _ConfigHandler(_Handler):
    def do_GET(self):
        if self.path == "/config.json":
            body = json.dumps({
                "ws_url":       f"ws://{self.headers.get('Host', '').split(':')[0]}:{WS_PORT}",
                "stream_url":   USTREAMER_URL,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

_Handler.__class__ = type(_Handler)  # keep original for HTTP
_ConfigHandler._web_dir = _Handler._web_dir

def _run_http_with_config(port: int) -> None:
    Path(_ConfigHandler._web_dir).mkdir(parents=True, exist_ok=True)
    srv = HTTPServer(("0.0.0.0", port), _ConfigHandler)
    log.info(f"HTTP (web UI): http://0.0.0.0:{port}")
    srv.serve_forever()

# ── Entry point ───────────────────────────────────────────────────
async def _main():
    # HTTP in background thread
    t = threading.Thread(
        target=_run_http_with_config, args=(HTTP_PORT,), daemon=True
    )
    t.start()

    # WebSocket server
    log.info(f"WebSocket: ws://0.0.0.0:{WS_PORT}")
    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    log.info(f"ESP32 target : {ESP_IP}:{ESP_PORT}")
    log.info(f"uStreamer URL: {USTREAMER_URL or '(not set)'}")
    asyncio.run(_main())
