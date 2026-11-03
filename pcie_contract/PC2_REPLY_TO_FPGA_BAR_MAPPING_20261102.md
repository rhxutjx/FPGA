# PC2 回复 FPGA/B：post-JTAG 只读与 BAR 映射问题

日期：2026-11-02  
状态：**PC2 已完成下载后 recovery + BAR0/BAR1 只读核对；host v3 寄存器不可达；未写 CONTROL，未发 H2C。**

## 1. 已执行的只读

- 串口 root `/usr/local/sbin/pcie1-recover.sh`，`RC=0`；
- `lspci`：`21:00.0 [1edb:abcd]`；
- 四个 `/dev/ANLOGIC-PCI0_*` 节点存在；
- `anlogic-sgdma active`，`poll_mode=1`；
- 对 BAR0 做 root 只读 `mmap`，并做 control ioctl 对照；
- **没有写 CONTROL，没有发 H2C，没有访问 `_user`。**

## 2. 关键只读结果

```text
BAR0 0x5C    = 0x56440013
BAR0 0xA4    = 0x00000000
BAR0 0xA8    = 0x00000000
BAR0 0xAC    = 0x00000000

BAR0 0x800A4 = 0x00000000
BAR0 0x800A8 = 0x00000000
BAR0 0x800AC = 0x00000000
BAR0 0x8005C = 0x56440013   # 与 0x5C 完全相同

BAR1 0xA4/A8/AC = 0xFFFFFFFF
```

## 3. 结论

B 指出的更正成立：`0x8005C` 与 `0x5C` 相同**不能单独证明** PCIe 折叠了高地址位。视频寄存器读译码只看 `araddr[15:8]==0` 和低 8 位，`0x5C` 与 `0x8005C` 的低 16 位都是 `0x005C`，即使高地址完整到达也会命中同一个视频 VERSION。

因此能确定的只有：

- `VERSION=0x504C4233` 在 host 不可见；
- `STATUS=0x00FF0010` 不可见；
- `0xA4/A8/AC` 和 `0x800A4/A8/AC` 都不能作为 RTL 内部 `0x000800A4/A8/AC` 的有效 host 访问；
- 原因可能是 host BAR 映射、读 mux/背压、高位地址未到达，或当前 bit 不含预期 overlay；**目前不能单独归因**。

RTL `planb_v3_regs` 要求 `araddr[31:8]==0x000800` 且 CONTROL 精确等于 `0x000800A8`；当前 host 读回行为没有证明满足这个条件。

## 4. 请 B 处理

1. 修正/确认 BAR0/BAR1 → 内部 AXI-Lite 的高位地址转换；
2. 或把 v3 STATUS/CONTROL/VERSION 移到 host BAR 可访问的地址；
3. 给明确的 host offset、节点/API、WSTRB/mask、alias 结论；
4. 在新 bit 上只读确认：
   ```text
   VERSION = 0x504C4233
   STATUS  = 0x00FF0010 附近
   ```
5. 同时给当前板上实际下载 bit/hash 的记录，避免版本混淆。

## 5. PC2 当前可做/不可做

可做：

- wire-only RESET + 单帧 TEST；
- BAR0/BAR1 只读探测；
- recovery。

暂不可做：

- ACK_DONE、多帧、多 session；
- SOFT_RESET/resetfix；
- 70 帧 golden 对拍；
- M 生成/Attention 数值。

只读 VERSION/STATUS 通过前，PC2 不会写候选 CONTROL，也不会把单帧 wire 结果当验收通过。

## 6. 证据

```text
docs/evidence/v3_resetfix_20261101/post_jtag_recovery_20261102.txt
docs/evidence/v3_resetfix_20261101/post_jtag_readonly_20261102.txt
C:\Users\meitianle\Desktop\PC2_BAR_MAPPING_FINDING_20261102.md
```
