#!/usr/bin/env python3
"""Experimental M resetfix probe: bad CRC -> write CONTROL.SOFT_RESET -> RESET+TEST.

No STATUS read/interpretation. This writes candidate CONTROL 0xA8; only run
after explicit authorization on the experimental M bit.
"""
import argparse
import fcntl
import os
import select
import signal
import struct
import sys
import time

sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101")
import multisession_v3 as codec

H2C = "/dev/ANLOGIC-PCI0_h2c_0"
C2H = "/dev/ANLOGIC-PCI0_c2h_0"
CTRL = "/dev/ANLOGIC-PCI0_control"
ANLOGIC_IOCW = (1 << 30) | (16 << 16) | (ord("x") << 8) | 4


class _Deadline(Exception):
    pass


def write_frame(frame, timeout=5.0):
    fd = os.open(H2C, os.O_WRONLY)
    try:
        old = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_Deadline()))
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            return os.write(fd, frame)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
    finally:
        os.close(fd)


def read_exact(count, timeout=5.0):
    fd = os.open(C2H, os.O_RDONLY | os.O_NONBLOCK)
    deadline = time.monotonic() + timeout
    out = bytearray()
    try:
        while len(out) < count:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"timeout {len(out)}/{count}")
            r, _, _ = select.select([fd], [], [], left)
            if not r:
                raise TimeoutError(f"timeout {len(out)}/{count}")
            chunk = os.read(fd, count - len(out))
            if chunk:
                out += chunk
        return bytes(out)
    finally:
        os.close(fd)


def control(value, offset):
    fd = os.open(CTRL, os.O_RDWR)
    try:
        req = struct.pack("<HHIII", 0, 0, offset, value, 0)
        fcntl.ioctl(fd, ANLOGIC_IOCW, req)
    finally:
        os.close(fd)


def reset_test(seq):
    reset = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                               position=0, session_id=255, payload=b"")
    write_frame(reset)
    ack = read_exact(32)
    h, p = codec.unpack_frame(ack, direction="c2h")
    if (h.op != codec.OP_RESET_CACHE or h.session_id != 255 or h.layer != 255
            or h.position != 0 or p):
        raise RuntimeError("RESET ACK mismatch")
    seq += 1
    payload = bytes((7 + 13 * i) & 0xFF for i in range(1920))
    test = codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0, position=0,
                              session_id=0, payload=payload)
    write_frame(test)
    raw = read_exact(1184)
    h, p = codec.unpack_frame(raw, direction="c2h")
    if (h.op != codec.OP_TEST or h.seq != seq or h.session_id != 0
            or h.layer != 0 or h.position != 0 or p != payload[:1152]):
        raise RuntimeError("TEST mismatch after soft reset")
    return seq


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=lambda s: int(s, 0), default=0xA8)
    args = parser.parse_args()
    seq = 1
    reset = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                               position=0, session_id=255, payload=b"")
    write_frame(reset)
    ack = read_exact(32)
    h, p = codec.unpack_frame(ack, direction="c2h")
    if (h.op != codec.OP_RESET_CACHE or h.session_id != 255 or h.layer != 255 or p):
        raise RuntimeError("initial RESET ACK mismatch")
    print("initial RESET ACK OK", flush=True)
    seq += 1
    bad = bytearray(codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0,
                                       position=0, session_id=0,
                                       payload=bytes(1920)))
    bad[24] ^= 0xFF
    write_frame(bytes(bad))
    time.sleep(0.2)
    print("bad CRC sent", flush=True)
    control(1, args.offset)  # SOFT_RESET
    print(f"CONTROL 0x{args.offset:x}=1 written", flush=True)
    time.sleep(0.1)
    next_seq = reset_test(seq + 1)
    print(f"RESET+TEST after SOFT_RESET OK next_seq={next_seq}", flush=True)


if __name__ == "__main__":
    main()


