#!/usr/bin/env python3
"""Read-only candidate v3 registers on BAR0; no writes, no control access."""
import fcntl
import os
import struct
import sys

IOCR = (2 << 30) | (16 << 16) | (ord('x') << 8) | 5
CTRL = "/dev/ANLOGIC-PCI0_control"
OFFSETS = [0x5C, 0xA4, 0xAC, 0x800A4, 0x800A8, 0x800AC, 0x8005C]


def read_bar(fd, bar_id, off):
    buf = bytearray(16)
    struct.pack_into("<HHIII", buf, 0, bar_id, 0, off, 0, 0)
    fcntl.ioctl(fd, IOCR, buf, True)
    return struct.unpack_from("<I", buf, 12)[0]


def main():
    fd = os.open(CTRL, os.O_RDWR)
    try:
        for off in OFFSETS:
            try:
                value = read_bar(fd, 0, off)
                print(f"BAR0 0x{off:02x} = 0x{value:08x}")
            except Exception as exc:
                print(f"BAR0 0x{off:02x} ERR {exc}", file=sys.stderr)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()

