#!/usr/bin/env python3
"""Standalone packet layout verifier — no external dependencies."""
import struct

PACKET_MAGIC = 0xCAFE
PACKET_SIZE  = 16
_seq = 0

def _next_seq():
    global _seq
    _seq += 1
    return _seq

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def make_mouse_packet(buttons, dx, dy, wheel, pan):
    pkt = struct.pack(
        "<HIBBBhhbbB",
        PACKET_MAGIC, _next_seq(), 0x01, 0,
        clamp(buttons, 0, 0xFF),
        clamp(dx, -32767, 32767),
        clamp(dy, -32767, 32767),
        clamp(wheel, -127, 127),
        clamp(pan, -127, 127),
        0,
    )
    assert len(pkt) == PACKET_SIZE
    return pkt

def make_keyboard_packet(modifiers, keycodes):
    keys = (list(keycodes) + [0] * 6)[:6]
    pkt = struct.pack(
        "<HIBBBBBBBBBB",
        PACKET_MAGIC, _next_seq(), 0x02, 0,
        clamp(modifiers, 0, 0xFF), 0,
        keys[0], keys[1], keys[2], keys[3], keys[4], keys[5],
    )
    assert len(pkt) == PACKET_SIZE
    return pkt

def make_consumer_packet(usage_id):
    pkt = struct.pack(
        "<HIBBHBBBBBB",
        PACKET_MAGIC, _next_seq(), 0x03, 0,
        clamp(usage_id, 0, 0xFFFF),
        0, 0, 0, 0, 0, 0,
    )
    assert len(pkt) == PACKET_SIZE
    return pkt

def check(name, got, expected):
    if got == expected:
        print(f"  PASS  {name}: {got.hex(' ')}")
    else:
        print(f"  FAIL  {name}")
        print(f"        got: {got.hex(' ')}")
        print(f"        exp: {expected.hex(' ')}")
        for i, (g, e) in enumerate(zip(got, expected)):
            if g != e:
                print(f"        byte[{i}]: 0x{g:02X} != 0x{e:02X}")
        raise AssertionError(f"{name} failed")

print("Verifying UDP packet layout against protocol.h ...\n")

# Mouse: buttons=0x03, dx=10, dy=-5, wheel=1, pan=0
# Offset: 0-1=magic(FE CA), 2-5=seq(01 00 00 00), 6=type(01), 7=res(00)
#         8=buttons(03), 9-10=dx(0A 00), 11-12=dy(FB FF),
#         13=wheel(01), 14=pan(00), 15=pad(00)
check("mouse", make_mouse_packet(0x03, 10, -5, 1, 0),
      bytes([0xFE,0xCA, 0x01,0x00,0x00,0x00, 0x01,0x00,
             0x03, 0x0A,0x00, 0xFB,0xFF, 0x01, 0x00, 0x00]))

# Keyboard: modifiers=0x03 (LCtrl+LShift), keycodes=[0x04,0x05]
# Offset: 8=mod(03), 9=res(00), 10-15=keycodes(04 05 00 00 00 00)
check("keyboard", make_keyboard_packet(0x03, [0x04, 0x05]),
      bytes([0xFE,0xCA, 0x02,0x00,0x00,0x00, 0x02,0x00,
             0x03, 0x00, 0x04,0x05,0x00,0x00,0x00,0x00]))

# Consumer: usage_id=0x00E9 (Volume Up)
# Offset: 8-9=usage_id(E9 00), 10-15=pad(00*6)
check("consumer", make_consumer_packet(0x00E9),
      bytes([0xFE,0xCA, 0x03,0x00,0x00,0x00, 0x03,0x00,
             0xE9,0x00, 0x00,0x00,0x00,0x00,0x00,0x00]))

print("\nAll tests passed.")
