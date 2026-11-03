import fcntl
import os
import struct

IOCR = (2 << 30) | (16 << 16) | (ord("x") << 8) | 5
CTRL = "/dev/ANLOGIC-PCI0_control"
fd = os.open(CTRL, os.O_RDWR)
try:
    for bar in (0, 1):
        for off in (0x00, 0x40, 0x44, 0x5C, 0x74, 0x84, 0xA4, 0xA8, 0xAC, 0xB0, 0xBC):
            buf = bytearray(16)
            struct.pack_into("<HHIII", buf, 0, bar, 0, off, 0, 0)
            try:
                fcntl.ioctl(fd, IOCR, buf, True)
                v = struct.unpack_from("<I", buf, 12)[0]
                print(f"BAR{bar} 0x{off:02x} = 0x{v:08x}")
            except Exception as exc:
                print(f"BAR{bar} 0x{off:02x} ERR {exc}")
finally:
    os.close(fd)
