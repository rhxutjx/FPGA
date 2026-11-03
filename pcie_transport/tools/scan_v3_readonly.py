#!/usr/bin/env python3
"""Read-only scan for v3 VERSION/STATUS at host BAR offsets; no writes."""
import fcntl
import os
import struct

IOCR = (2 << 30) | (16 << 16) | (ord("x") << 8) | 5
CTRL = "/dev/ANLOGIC-PCI0_control"
TARGETS = {0x504C4233: "VERSION", 0x00FF0010: "STATUS_READY",
           0x00FF0001: "STATUS_DONE", 0x00FF0026: "STATUS_CRC_FAULT"}

fd = os.open(CTRL, os.O_RDWR)
try:
    for bar, limit in ((0, 0x100000), (1, 0x10000)):
        step = 4
        matches = []
        for off in range(0, limit, step):
            buf = bytearray(16)
            struct.pack_into("<HHIII", buf, 0, bar, 0, off, 0, 0)
            try:
                fcntl.ioctl(fd, IOCR, buf, True)
            except OSError as exc:
                print(f"BAR{bar} stop at 0x{off:x}: {exc}")
                break
            v = struct.unpack_from("<I", buf, 12)[0]
            if v in TARGETS:
                matches.append((off, v, TARGETS[v]))
        print(f"BAR{bar} matches:")
        for off, v, name in matches:
            print(f"  0x{off:06x} = 0x{v:08x} {name}")
        if not matches:
            print("  none")
finally:
    os.close(fd)
