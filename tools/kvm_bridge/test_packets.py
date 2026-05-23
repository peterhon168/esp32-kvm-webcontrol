#!/usr/bin/env python3
"""Verify UDP packet layout matches ESP32 protocol.h"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Import packet builders directly
from server import make_mouse_packet, make_keyboard_packet, make_consumer_packet, PACKET_SIZE

def check(name, pkt, expected_bytes):
    assert len(pkt) == PACKET_SIZE, f"{name}: size {len(pkt)} != {PACKET_SIZE}"
    for i, (got, exp) in enumerate(zip(pkt, expected_bytes)):
        assert got == exp, f"{name}: byte[{i}] = 0x{got:02X}, expected 0x{exp:02X}"
    print(f"  PASS  {name}: {pkt.hex(' ')}")

print("Testing packet layout against protocol.h...\n")

# ── Mouse: buttons=0x03 (L+R), dx=10, dy=-5, wheel=1, pan=0 ──────
# magic=0xCAFE(LE)=FE CA, seq=1=01 00 00 00, type=01, res=00
# buttons=03, dx=10=0A 00, dy=-5=FB FF, wheel=01, pan=00, pad=00
pkt = make_mouse_packet(0x03, 10, -5, 1, 0)
check("mouse", pkt, [
    0xFE, 0xCA,             # magic LE
    0x01, 0x00, 0x00, 0x00, # seq=1
    0x01,                   # type=mouse
    0x00,                   # reserved
    0x03,                   # buttons
    0x0A, 0x00,             # dx=10 (int16 LE)
    0xFB, 0xFF,             # dy=-5 (int16 LE)
    0x01,                   # wheel=1
    0x00,                   # pan=0
    0x00,                   # pad
])

# ── Keyboard: LCtrl+LShift=0x03, keycodes=[0x04,0x05,0,0,0,0] ────
# magic=FE CA, seq=2, type=02, res=00
# mod=03, res=00, 04 05 00 00 00 00
pkt = make_keyboard_packet(0x03, [0x04, 0x05])
check("keyboard", pkt, [
    0xFE, 0xCA,
    0x02, 0x00, 0x00, 0x00,
    0x02,
    0x00,
    0x03,                   # modifiers
    0x00,                   # reserved
    0x04, 0x05, 0x00, 0x00, 0x00, 0x00,  # keycodes[6]
])

# ── Consumer: usage_id=0x00E9 (Volume Up) ─────────────────────────
pkt = make_consumer_packet(0x00E9)
check("consumer", pkt, [
    0xFE, 0xCA,
    0x03, 0x00, 0x00, 0x00,
    0x03,
    0x00,
    0xE9, 0x00,             # usage_id LE
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  # pad[6]
])

print("\nAll packet tests passed.")
