"""
ESP32-S3 KVM - Server (Windows)

Captures keyboard events (LL Hook) and mouse events (Raw Input + LL Hook)
and sends them as UDP packets to ESP32-S3.

Usage:
    python server.py --host <ESP32_IP> [--port 4210] [--rate 125]
"""

import argparse
import sys
import threading

from protocol import UDP_PORT
from state import InputState
from udp_sender import sender_thread
from winapi_hooks import InputHookManager

def main():
    parser = argparse.ArgumentParser(
        description="ESP32-S3 KVM Server (KVM via Scroll Lock)"
    )
    parser.add_argument("--host", required=True, help="ESP32 IP address")
    parser.add_argument("--port", type=int, default=UDP_PORT,
                        help=f"UDP port (default: {UDP_PORT})")
    parser.add_argument("--rate", type=int, default=125,
                        help="Polling rate in Hz (default: 125)")
    parser.add_argument("--jiggle", action="store_true",
                        help="Enable invisible mouse jiggler to prevent PC from sleeping")
    args = parser.parse_args()

    if not (60 <= args.rate <= 1000):
        print("ERROR: --rate must be between 60 and 1000", file=sys.stderr)
        sys.exit(1)

    stop_event = threading.Event()
    state = InputState()

    print("[INIT] Starting sender thread...")
    sender = threading.Thread(
        target=sender_thread,
        args=(args.host, args.port, args.rate, stop_event, state, args.jiggle),
        daemon=True,
    )
    sender.start()

    print("[INIT] Installing WinAPI hooks...")
    hook_manager = InputHookManager(state)
    try:
        hook_manager.start()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        stop_event.set()
        sys.exit(1)

    print("[HOOKS] Keyboard LL + Mouse LL hooks installed")
    print("[KVM] Press Scroll Lock to toggle KVM mode")
    print("[KVM] OFF (input goes to Host PC)")

    try:
        hook_manager.process_messages()
    except KeyboardInterrupt:
        print("\n[MAIN] Shutting down...")

    # Cleanup
    stop_event.set()
    hook_manager.stop()
    sender.join(timeout=2)
    print("[MAIN] Done")

if __name__ == "__main__":
    main()
