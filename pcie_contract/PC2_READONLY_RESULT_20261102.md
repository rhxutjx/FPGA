# PC2 只读核对结果（2026-11-02）

对象：B v2 handoff，当前板上按 B 记录为 M dual GQA `044DBC7E...0299`；PC2 未能从板上回读 bitstream hash。  
操作：只读；**未写 CONTROL，未发 H2C**。

## 1. 板端状态

```text
lspci: 21:00.0 [1edb:abcd]
/dev/ANLOGIC-PCI0_user/control/h2c_0/c2h_0: 存在
anlogic-sgdma: active
poll_mode: 1
```

BAR0：

```text
0x5C = 0x56440013       (旧 v2 VERSION)
0xA4 = 0x00000000       (期望 STATUS 0x00FF0010)
0xA8 = 0x00000000
0xAC = 0x00000000       (期望 VERSION 0x504C4233)
0x800A4 = 0x00000000
0x800A8 = 0x00000000
0x800AC = 0x00000000
0x8005C = 0x56440013
```

BAR1：

```text
0xA4/A8/AC/B0/BC = 0xFFFFFFFF
```

原始输出：`docs/evidence/v3_resetfix_20261101/readonly_check_20261102.txt`

## 2. 结论

**只读核对未通过。**

- 没有在 host `0xA4/0xAC` 读到 B 文档中的 `STATUS=0x00FF0010` / `VERSION=0x504C4233`；
- `0x800A4/0x800AC` 也为 0；
- BAR1 不可用；
- `0x5C` 仍是旧 v2 VERSION，不能标识 v3 应用寄存器；
- 因此无法确认 `BAR0/BAR1 → 0x000800A4/A8/AC` 的 host 映射。

按 B 的前置条件，**只读未通过前不能推进 CONTROL 和 70 帧对拍**。

## 3. 请 B 处理

1. 确认当前板上实际 bit 和烧录记录（B v2 记录为 M dual GQA `044D...`，但没有板上回读）。
2. 给 `BAR0/BAR1` 到内部 `0x000800A4/A8/AC` 的真实 offset/API/WSTRB/alias；不能只给内部地址。
3. 若 B 认为 host 映射应为 `0xA4/0xA8/0xAC`，请在新 bit 上做一次只读回读，确认 `0xAC=0x504C4233`、`0xA4=0x00FF0010`；当前板子读不到。
4. 确认前 PC2 不写 CONTROL，不做 ACK_DONE/多帧/SOFT_RESET/70 帧。

## 4. 当前板状态

已执行串口 root `pcie1-recover.sh`；端点/节点/服务存在。  
没有遗留 host 进程，也没有写候选寄存器。
