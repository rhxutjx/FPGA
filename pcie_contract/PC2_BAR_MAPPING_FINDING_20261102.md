# PC2 host BAR 映射只读测试结果（2026-11-02）

对象：当前板上 M bit（B 记录为 M dual GQA `044D...`）；操作：**只读，root mmap BAR0，无写**。

## 1. 方法

串口 root 下对：

```text
/sys/bus/pci/devices/0000:21:00.0/resource0
```

做 1 MiB 只读 `mmap`，直接读取 BAR0 原始偏移；同时用 control ioctl 做对照。  
脚本：`pcie_transport/tools/mmap_bar_scan.py`。

## 2. 原始结果

```text
BAR0 mmap 0x000040 = 0x00000002
BAR0 mmap 0x00005C = 0x56440013
BAR0 mmap 0x000074 = 0x00000C01
BAR0 mmap 0x000084 = 0x00002001

BAR0 mmap 0x0000A4 = 0x00000000
BAR0 mmap 0x0000A8 = 0x00000000
BAR0 mmap 0x0000AC = 0x00000000

BAR0 mmap 0x0800A4 = 0x00000000
BAR0 mmap 0x0800A8 = 0x00000000
BAR0 mmap 0x0800AC = 0x00000000
BAR0 mmap 0x08005C = 0x56440013
```

## 3. 发现

1. 旧 v2 `0x5C` 在 host BAR0 可读；
2. `0x8005C` 读回同一个 `0x56440013`；
3. `0x800A4/0x800AC` 均为 0，没有 v3 的 `STATUS/VERSION`；
4. `0xA4/0xAC` 也为 0；
5. BAR1 对应区域为 `0xFFFFFFFF`。

**重要更正（B 指出）：`0x8005C` 与 `0x5C` 相同不能单独证明 PCIe 折叠高地址位。**  
`imx415_pcie_top.v` 的视频寄存器读译码（约 line 925）只看 `m_axil_araddr[15:8]==0` 和低 8 位；`0x5C` 和 `0x8005C` 的低 16 位都是 `0x005C`，所以即使高位完整到达，也会返回同一个视频 VERSION。这个观测只能说明该路径命中视频寄存器，不能推断高地址被折叠。

## 4. 结论

当前 host BAR0 **没有证明能到达** RTL 内部：

```text
0x000800A4 / 0x000800A8 / 0x000800AC
```

`0x800A4/0x800AC` 读 0 的可能原因包括：host BAR 映射不对、读 mux/背压未选中 v3 overlay、内部高位地址未到达，或当前 bit 未包含预期 overlay；**目前没有足够证据把原因单独归为“高地址被折叠”**。

所以结论只能是：**host v3 STATUS/VERSION 不可见，映射/读返回路径仍需 B 确认；不能进入 CONTROL 或 70 帧。**

## 5. 需要 B 做

1. 把 v3 STATUS/CONTROL/VERSION 放到 host BAR0 可访问的地址，或修正 PCIe BAR→AXI 高位地址映射；
2. 明确 BAR0/BAR1、host offset、内部地址、WSTRB/mask、alias；
3. 在新 bit 上只读验证 `VERSION=0x504C4233`、`STATUS`，再谈 CONTROL。

在此之前 PC2 不写 CONTROL，不进入 resetfix/70 帧。
