# PC2 记录：下载后 recovery 与只读访问

日期：2026-11-02  
状态：只读；未写 CONTROL，未发 H2C。

## 1. 与下载的关系

- B v2 记录：JTAG 下载 `E:\KVmix\batch_v3_m_gqa_bram3_20261102\v3_m_experimental.bit`，SHA256 `044DBC7E...0299`；
- B TD 截图：`PH1A90` JTAG 下载成功；
- 截图无时间戳，B 未提供精确下载时间/回读；
- PC2 本次 recovery/只读发生在 B 通知下载完成后的窗口内；无法独立证明下载之后没有重配/断电。

## 2. Recovery

| 项 | 值 |
|---|---|
| PC 本地时间 | 2026-11-02 21:51 +08:00 |
| 板端时间 | 2026-04-27 21:14:33 UTC（板钟不可靠） |
| 命令 | 串口 root `/usr/local/sbin/pcie1-recover.sh` |
| 退出 | `RC=0` |
| 原始 log | `docs/evidence/v3_resetfix_20261101/post_jtag_recovery_20261102.txt` |

恢复后：

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

## 3. 只读 API

| 项 | 值 |
|---|---|
| 设备节点 | `/dev/ANLOGIC-PCI0_control` |
| 打开方式 | `os.open(node, O_RDWR)` |
| ioctl | `ANLOGIC_IOCR = 0x80107805` |
| 请求结构 | `<HHIII>`：`bar_id, 0, offset, 0, 0` |
| 返回读取 | 结构 offset 12 的 u32 |
| BAR id | `0`（BAR0）和 `1`（BAR1） |
| 访问宽度 | 32-bit |
| WSTRB | 无写操作，未使用 |
| `_user` 节点 | 未访问（此前 pread 会段错误） |

脚本：

```text
read_v3_candidate_regs.py  SHA256 4268a097...8f950d
read_v3_bar1.py            SHA256 8228f8ac...b3b5
```

## 4. BAR/offset 与返回值

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

原始输出：

```text
docs/evidence/v3_resetfix_20261101/post_jtag_readonly_20261102.txt
```

## 5. 结论

- `VERSION=0x504C4233` 未在 host 候选地址出现；
- `STATUS=0x00FF0010` 未出现；
- `0x5C/0x8005C=0x56440013` 只是视频寄存器路径；`0x8005C` 与 `0x5C` 相同不能证明高位折叠；
- host 到内部 `0x000800A4/A8/AC` 的路径仍未确认；
- 只读核对未通过，不能推进 CONTROL/70 帧。

## 6. 边界

- 没有写候选 CONTROL；
- 没有发 H2C；
- 没有访问 `_user`；
- 没有把 wire-only 单帧当 resetfix/Attention 验收。
