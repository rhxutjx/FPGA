# PC2 BAR 只读诊断结果（2026-11-02）

对象：B 的 **M BAR diagnostic bit**  
文件：`v3_m_experimental.bit`  
SHA256：`BA1357402D2BAAEDEC1CC7EB1CF7BD0D511B6EAE026EC0FE953F1E5E3BD9F7B1`

状态：**只读；未写 CONTROL/未发 H2C。诊断 bit 明确禁用 CONTROL 写入。**

## 1. 板端

```text
lspci: 21:00.0 [1edb:abcd]
/dev/ANLOGIC-PCI0_control 存在
anlogic-sgdma active
BAR0 0xAC = 0x504C4433   (PLD3 diagnostic marker)
BAR0 0xA4 = 0x00FF0010   (diagnostic STATUS)
BAR0 0xB0 = 上一笔 AXI-Lite 读地址
```

## 2. 探针

使用 B 提供的 `probe_bar_readonly.py`，通过 PC2 已验证的：

```text
/dev/ANLOGIC-PCI0_control
ANLOGIC_IOCR = 0x80107805
bar_id = 0
```

只读；没有写。

输出：

```json
{
  "version_offset": "0xac",
  "version": "0x504c4433",
  "measurements": [
    {"target": "0x5c",    "read_value": "0x56440013", "previous_axil_address": "0x2120005c"},
    {"target": "0x8005c", "read_value": "0x56440013", "previous_axil_address": "0x2128005c"},
    {"target": "0xac",    "read_value": "0x504c4433", "previous_axil_address": "0x212000ac"},
    {"target": "0x800ac", "read_value": "0x504c4433", "previous_axil_address": "0x212800ac"}
  ],
  "status": "diagnostic marker observed; compare trace with independently verified expected traffic"
}
```

## 3. 可确认的 host BAR 映射

`B0` 返回上一笔被用户 AXI-Lite 接受的读地址；结果显示：

```text
BAR0 offset 0x5C     -> AXI 0x2120005C
BAR0 offset 0x8005C  -> AXI 0x2128005C
BAR0 offset 0xAC     -> AXI 0x212000AC
BAR0 offset 0x800AC  -> AXI 0x212800AC
```

即：

- host BAR0 的物理基址 `0x21200000` **被包含在用户 AXI-Lite 地址里**；
- `0x80000` 位也保留：`0x2128005C/AC`；
- **不是高低位折叠**；诊断 bit 的 low16 译码使两者都命中；
- 实际 AXI 地址分别为 `0x212000xx` 和 `0x212800xx`。

## 4. 为什么功能版读不到

功能版 `planb_v3_regs` 要求：

```text
araddr[31:8] == 0x000800
```

但实际 host BAR0 访问给出：

```text
0x212000AC / 0x212800AC
```

`[31:8]` 分别是 `0x212000` / `0x212800`，不是 `0x000800`。  
所以功能版 v3 STATUS/CONTROL/VERSION 从未命中；`0xA4/AC` 读 0 是 **功能版地址译码与实际 AXI 地址不匹配**，不是 host 高位折叠，也不是没有访问到 FPGA。

## 5. 需要 B 修正

功能版至少需要二选一：

1. 把 `planb_v3_regs` 译码改为实际 host AXI 页：
   ```text
   BAR0 0x212000A4/A8/AC
   BAR0 0x212800A4/A8/AC（如需要）
   ```
2. 或在 PCIe/BAR 层把用户 AXI 地址转换到 `0x000800A4/A8/AC`；host 侧无法自行改变物理 BAR 基址。

建议 **不要在 host 侧猜 offset**；按实际 AXI 地址修 RTL 最直接。诊断 bit 已证明 high bits 是保留的。

## 6. 下一步

1. B 生成功能版：译码匹配 `0x212000A4/A8/AC`（以及需要的高位页）；
2. PC2 只读确认 `VERSION=0x504C4233`、`STATUS`；
3. 再做 RESET/TEST、ACK_DONE、多 session、SOFT_RESET；
4. 最后再用 70 帧 golden。

当前诊断 bit 禁用了 CONTROL，不能用来验收 resetfix/多帧。
