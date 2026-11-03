import os
import struct

fd = os.open("/dev/ANLOGIC-PCI0_user", os.O_RDONLY)
for off in (0xA4, 0xA8, 0xAC, 0x800A4, 0x800A8, 0x800AC, 0x8005C):
    try:
        v = struct.unpack("<I", os.pread(fd, 4, off))[0]
        print(hex(off), hex(v))
    except Exception as exc:
        print(hex(off), "ERR", exc)
os.close(fd)
