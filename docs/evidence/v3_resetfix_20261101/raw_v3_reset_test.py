#!/usr/bin/env python3
"""Raw v3 RESET + one TEST over SGDMA; no STATUS/CONTROL access."""
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


def main():
    seq = 1
    reset = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                               position=0, session_id=255, payload=b"")
    n = write_frame(reset)
    print(f"RESET write {n}/{len(reset)}")
    ack = read_exact(32)
    h, p = codec.unpack_frame(ack, direction="c2h")
    print(f"RESET ACK op={h.op} session={h.session_id} layer={h.layer} seq={h.seq} payload={len(p)}")
    seq += 1
    payload = bytes((7 + 13 * i) & 0xFF for i in range(1920))
    test = codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0, position=0,
                              session_id=0, payload=payload)
    n = write_frame(test)
    print(f"TEST write {n}/{len(test)}")
    raw = read_exact(1184)
    rh, rp = codec.unpack_frame(raw, direction="c2h")
    print(f"TEST ACK op={rh.op} session={rh.session_id} layer={rh.layer} pos={rh.position} seq={rh.seq} match={rp == payload[:1152]}")


if __name__ == "__main__":
    main()
