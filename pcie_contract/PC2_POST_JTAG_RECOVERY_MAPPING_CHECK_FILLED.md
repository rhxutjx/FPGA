# PC2 填写：下载后 PCIe 恢复、只读核验与映射待确认项

日期：2026-11-02  
状态：**PC2 已执行 post-JTAG recovery + 只读检查；host VERSION/STATUS 仍不可见；只读未通过。**

## 1. 下载证据

B 提供 TD 截图，显示：

```text
download -bit ...batch_v3_m_gqa_bram3_20261102\v3_m_experimental.bit -mode jtag
Chip validation success: PH1A90
Downloading succeeded!
```

B v2 给的文件 SHA256：

```text
044DBC7ED5ECF1A742BCF759A81E17BFCED47D6130335FCA4FEEF13E4E750299
```

PC2 无法从板上回读 bitstream hash；截图无时间戳，且不能证明之后未断电/重配置。  
PC2 只能确认：本次只读是在 B 通知下载完成后的最后一次 recovery 之后执行。

## 2. Recovery 记录

- PC 本地时间：2026-11-02 21:51 +08:00
- 命令：串口 root `/usr/local/sbin/pcie1-recover.sh`
- 退出：`RC=0`
- 板端时间：2026-04-27 21:14:33 UTC（板钟不可靠）
- uptime：1:25
- 原始 log：`docs/evidence/v3_resetfix_20261101/post_jtag_recovery_20261102.txt`

## 3. 恢复后状态

```text
lspci -nn -s 21:00.0:
21:00.0 [1edb:abcd]

/dev/ANLOGIC-PCI0_user
/dev/ANLOGIC-PCI0_control
/dev/ANLOGIC-PCI0_h2c_0
/dev/ANLOGIC-PCI0_c2h_0

anlogic-sgdma active
poll_mode = 1
```

## 4. 只读访问方式

- 节点：`/dev/ANLOGIC-PCI0_control`
- ioctl：`ANLOGIC_IOCR = 0x80107805`
- 结构：`<HHIII>`，`bar_id, 0, offset, 0, 0`；读取 offset 12
- bar_id：0（BAR0）和 1（BAR1）
- 偏移：
  - BAR0/BAR1：`0x5C, 0xA4, 0xA8, 0xAC, 0x800A4, 0x800A8, 0x800AC, 0xB0, 0xBC`
- **未访问 `_user` 节点；未写 CONTROL；未发 H2C；WSTRB 无写操作，未使用。**
- 脚本 SHA256：
  - `read_v3_candidate_regs.py`：`4268a0972335ac3acd1626276c32094f81e28df9edd0bd95ac7b0784b38f950d`
  - `read_v3_bar1.py`：`8228f8aca14b16602bdbdd63abfadc5c27924b19c5786afbb605f2e20430b3b5`
- 原始输出：`docs/evidence/v3_resetfix_20261101/post_jtag_readonly_20261102.txt`

## 5. 原始返回值

```text
BAR0 0x5C    = 0x56440013
BAR0 0xA4    = 0x00000000
BAR0 0xA8    = 0x00000000
BAR0 0xAC    = 0x00000000
BAR0 0x800A4 = 0x00000000
BAR0 0x800A8 = 0x00000000
BAR0 0x800AC = 0x00000000
BAR0 0x8005C = 0x56440013

BAR1 0xA4    = 0xFFFFFFFF
BAR1 0xA8    = 0xFFFFFFFF
BAR1 0xAC    = 0xFFFFFFFF
BAR1 0xB0    = 0xFFFFFFFF
BAR1 0xBC    = 0xFFFFFFFF
```

## 6. 结论

- `VERSION=0x504C4233` 未在 host 候选 offset 出现；
- `STATUS=0x00FF0010` 未出现；
- `0x5C=0x56440013` 只是旧 v2 VERSION，不能证明 v3 应用寄存器；
- host `A4/A8/AC` / `800A4/800A8/800AC` 均未验证；
- 只读核对 **失败**，不能进入 CONTROL、ACK_DONE、SOFT_RESET 或 70 帧验收。

## 7. 下一步

1. B 确认当前板上实际 bit hash 和下载/重配置记录；
2. B 给 BAR0/BAR1 → 内部 `0x000800A4/A8/AC` 的真实 offset/API/WSTRB/alias；
3. 或 B 在新 bit 上完成只读回读，确认 `0xAC=0x504C4233`、`0xA4=0x00FF0010`；
4. 只读通过前 PC2 不写 CONTROL，不进入 resetfix/70 帧。
