#!/usr/bin/env python3
"""Raw v3: RESET, TEST session0, candidate ACK_DONE 0xA8=4, TEST session1/2."""
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


def control(value):
    fd = os.open(CTRL, os.O_RDWR)
    try:
        fcntl.ioctl(fd, ANLOGIC_IOCW, struct.pack("<HHIII", 0, 0, 0xA8, value, 0))
    finally:
        os.close(fd)


def main():
    seq = 1
    reset = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                               position=0, session_id=255, payload=b"")
    write_frame(reset)
    ack = read_exact(32)
    h, p = codec.unpack_frame(ack, direction="c2h")
    if h.op != codec.OP_RESET_CACHE or h.session_id != 255 or h.layer != 255 or p:
        raise RuntimeError("RESET ACK mismatch")
    print("RESET ACK OK", flush=True)
    seq += 1
    for session in (0, 1, 2):
        payload = bytes((session * 17 + 3 + 11 * i) & 0xFF for i in range(1920))
        frame = codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0,
                                   position=0, session_id=session, payload=payload)
        write_frame(frame)
        raw = read_exact(1184)
        h, p = codec.unpack_frame(raw, direction="c2h")
        ok = (h.op == codec.OP_TEST and h.seq == seq and h.session_id == session
              and h.layer == 0 and h.position == 0 and p == payload[:1152])
        print(f"TEST session={session} seq={seq} ok={ok}", flush=True)
        if not ok:
            raise RuntimeError("TEST mismatch")
        if session != 2:
            control(4)
            print("ACK_DONE 0xA8=4 written", flush=True)
            time.sleep(0.01)
        seq += 1


if __name__ == "__main__":
    main()
