import mmap
import os
import struct

path = "/sys/bus/pci/devices/0000:21:00.0/resource0"
fd = os.open(path, os.O_RDONLY | os.O_SYNC)
try:
    mm = mmap.mmap(fd, 0x100000, mmap.MAP_SHARED, mmap.PROT_READ)
    for off in (0x40, 0x5C, 0x74, 0x84, 0xA4, 0xA8, 0xAC, 0x800A4, 0x800A8, 0x800AC, 0x8005C):
        value = struct.unpack_from("<I", mm, off)[0]
        print(f"mmap 0x{off:06x} = 0x{value:08x}")
    mm.close()
finally:
    os.close(fd)
