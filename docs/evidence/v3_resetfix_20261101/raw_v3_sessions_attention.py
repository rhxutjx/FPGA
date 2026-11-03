#!/usr/bin/env python3
"""Raw v3 TEST sessions 0/1/2 or one Attention over SGDMA.

No STATUS/CONTROL access. This only proves wire delivery/echo; it is not a
numeric Attention or KV-isolation acceptance.
"""
import argparse
import hashlib
import os
import select
import signal
import struct
import sys
import time
from pathlib import Path

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


def send_reset(seq):
    frame = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                               position=0, session_id=255, payload=b"")
    write_frame(frame)
    ack = read_exact(32)
    h, p = codec.unpack_frame(ack, direction="c2h")
    if (h.op != codec.OP_RESET_CACHE or h.session_id != 255 or h.layer != 255
            or h.position != 0 or p):
        raise RuntimeError("bad RESET ACK")
    print("RESET ACK OK", flush=True)
    return seq + 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("test", "attention"), default="test")
    args = parser.parse_args()
    seq = send_reset(1)
    if args.mode == "test":
        for session in (0, 1, 2):
            payload = bytes((session * 31 + 7 + 13 * i) & 0xFF for i in range(1920))
            frame = codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0,
                                       position=0, session_id=session, payload=payload)
            write_frame(frame)
            raw = read_exact(1184)
            h, p = codec.unpack_frame(raw, direction="c2h")
            ok = (h.op == codec.OP_TEST and h.seq == seq and h.session_id == session
                  and h.layer == 0 and h.position == 0 and p == payload[:1152])
            print(f"TEST session={session} seq={seq} ok={ok} response_sha={hashlib.sha256(raw).hexdigest()[:16]}",
                  flush=True)
            if not ok:
                raise RuntimeError("TEST response mismatch")
            seq += 1
    else:
        qkv_path = Path(sys.argv[0]).resolve().parent / "qkv" / "r0_p000_l00.fp16.bin"
        # Also accept the known board path used by the capture.
        alt = Path("/home/kvdev/work_pc2_pcie/qkv_export_20261101/run_3p_20261101/qkv/r0_p000_l00.fp16.bin")
        payload = (qkv_path if qkv_path.is_file() else alt).read_bytes()
        if len(payload) != 1920:
            raise RuntimeError("wrong QKV file")
        frame = codec.pack_request(seq=seq, op=codec.OP_ATTENTION, layer=0,
                                   position=0, session_id=0, payload=payload)
        write_frame(frame)
        raw = read_exact(1184)
        h, p = codec.unpack_frame(raw, direction="c2h")
        ok = (h.op == codec.OP_ATTENTION and h.seq == seq and h.session_id == 0
              and h.layer == 0 and h.position == 0 and len(p) == 1152)
        print(f"ATTENTION session=0 layer=0 pos=0 seq={seq} header_ok={ok} "
              f"response_sha={hashlib.sha256(raw).hexdigest()}", flush=True)
        if not ok:
            raise RuntimeError("ATTENTION response mismatch")


if __name__ == "__main__":
    main()
