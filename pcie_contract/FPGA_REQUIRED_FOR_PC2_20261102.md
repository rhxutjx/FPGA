# FPGA/B 需要提供或确认的材料

日期：2026-11-02  
对象：FPGA/B 侧  
目的：让 PC2 能对最终 M v3 bit 做只读、RESET/TEST、ACK_DONE、多 session、SOFT_RESET/resetfix、Attention/KV 和后续 M 生成验证。  
原则：**没有确认的 host BAR 映射，PC2 不写 CONTROL；不猜地址。**

## 0. 当前 PC2 实测状态（供 B 对照）

最后确认烧录完成、串口 root recovery 后：

```text
lspci: 21:00.0 [1edb:abcd] 存在
/dev/ANLOGIC-PCI0_* 存在
anlogic-sgdma active

BAR0 0x5C = 0x56440013
BAR0 0xA4 = 0x00000000
BAR0 0xAC = 0x00000000
BAR0 0x800A4 = 0x00000000
BAR0 0x800A8 = 0x00000000
BAR0 0x800AC = 0x00000000

v3 RESET 32B ACK OK
v3 TEST session0 seq=2 payload match=True
```

结论：**wire-only 单帧可用；host STATUS/CONTROL/VERSION 不可用；多帧/soft reset/resetfix 不能测。**

## 1. P0：不提供就阻塞

### 1.1 当前板上到底是哪一版

| 项 | 请填 |
|---|---|
| 模式 | B / M |
| B 侧完整路径 | |
| 完整 SHA256 | |
| 烧录时间/操作者 | |
| JTAG / Flash | |
| 烧录后 recovery 命令/结果 | |
| 当前板上实际 VERSION | |
| 当前板上实际 STATUS | |
| 已知可回退 bit | |

已知候选：

```text
M: E:\KVmix\batch_v3_m_resetfix_20261101\v3_m_experimental.bit
   8291B81385E3705D3B8887EE9DA544712BC55F598992AB0AB53737800035AAE4
B: E:\KVmix\batch_v3_b_resetfix_20261101\v3_b_experimental.bit
   D24B109D6E61CD180CBEB763F44F0E29393632521C8739BDC1C55B6A2F2F52AB
```

请明确当前板上是否是这两个之一，还是更新的 build。

### 1.2 Host BAR → 内部 AXI-Lite 的真实映射（最关键）

内部候选已知：

```text
STATUS  0x000800A4
CONTROL 0x000800A8
VERSION 0x000800AC
```

但 **host 侧实际映射没有确认**。请给下表，不要只给内部地址：

| 寄存器 | BAR0/BAR1 | host offset | 内部地址 | 读/写 | 位宽 | WSTRB/mask | 副作用/alias |
|---|---|---|---:|---|---:|---|---|
| STATUS | | `0x____` | `0x000800A4` | R | 32 | | |
| CONTROL | | `0x____` | `0x000800A8` | W | 32 | `0xF`? | |
| VERSION | | `0x____` | `0x000800AC` | R | 32 | | |

同时请确认：

- 用 `control` ioctl、`user` pread/pwrite，还是别的节点/API；
- 是否需要加 `0x80000` 基址；
- 高地址/vendor bank alias 是否仍存在；
- 读是否有副作用；
- 非法写/组合位的准确行为；
- 错误地址是否会落到 vendor RAM。

**PC2 当前实测**：`0xA4/0xAC=0`，`0xA8/0x800A8` 仍像 vendor RAM alias。  
如果 B 认为 mapping 已经是 `BAR0+0xA4/A8/AC`，请在板上只读确认 `VERSION=0x504C4233`；如果不是，请给真实 offset。

### 1.3 resetfix 的验收序列和期望值

请给可直接执行的序列：

```text
RESET_CACHE
-> TEST
-> 坏 CRC
-> FAULT
-> CONTROL.SOFT_RESET
-> READY
-> RESET_CACHE
-> TEST
```

并明确：

- `SOFT_RESET` 合法写值/bit；
- `ACK_DONE` 合法条件；
- 写后先 `RESET_BUSY` 还是直接 `READY`；
- `FAULT/ERR` 清除条件；
- 期望 `FAULT_CODE/LAST_SESSION`（当前 0/255 还是已实现）；
- 真实 DDR 掉线与应用复位如何区分；
- 失败时保留哪些状态/日志。

### 1.4 测试窗口和恢复

| 项 | 请填 |
|---|---|
| 独占窗口时间 | |
| 谁烧录/恢复 | |
| 串口 root 是否可用 | |
| `poll_mode` 用 0 还是 1 | |
| 回退 bit/恢复命令 | |
| 失败后谁处理 | |

## 2. P1：影响验收或后续 M 效果

### 2.1 时序/CDC 状态

请确认：

- B/M setup/hold WNS、STA coverage；
- no-clock / dummy-node / PLL-clock-buffer HIGH 是否接受；
- CDC/异步 FIFO/复位是否签核；
- 这是实验候选还是可验收版。

已知 M resetfix `+0.069/+0.012 ns`、STA 99.50%，B `+0.073/+0.020 ns`；均有 HIGH，不能称签核。

### 2.2 B bit

做 B/M 对比需要 B bit 的同一套信息：

- 文件/hash/烧录记录；
- host 映射；
- RESET/TEST/FAULT/soft reset 证据；
- 与 M 相同顺序。

### 2.3 独立 golden / M closed-loop

PC2 已有 3 条独立 prompt QKV（3150 帧），但来源是 **RK NPU post-RoPE + CPU F32 attention 反馈**，不是 M closed-loop。

请 B 给：

- 同 3 条 prompt 的 M Attention 输出 golden（session/layer/position 顺序、hash、策略）；
- 或确认 PC2 用 M bit 重新采集 closed-loop QKV；
- 以及独立生成方式/源码版本。

### 2.4 计数器（可选）

如果要 DDR/Attention 计数，请给：

- BAR/offset；
- 64-bit 快照语义；
- reset 行为；
- 是否在本 bit 中实现。

当前 `0xB0..0xBC` 未确认，PC2 不访问。

## 3. 请 B 直接回复的模板

```text
当前板上 bit：
  mode = B/M
  path =
  sha256 =
  烧录方式/时间/操作者 =
  当前 VERSION =
  当前 STATUS =

Host mapping：
  STATUS: BAR_ + offset -> internal 0x000800A4; API; width; side effects
  CONTROL: BAR_ + offset -> internal 0x000800A8; WSTRB/mask; legal values
  VERSION: BAR_ + offset -> internal 0x000800AC

resetfix 验收：
  RESET/TEST/坏 CRC/FAULT/SOFT_RESET 期望序列 =
  期望 STATUS/ERR/FAULT_CODE/LAST_SESSION =
  失败日志/回退 =

时序/CDC：
  WNS/coverage/HIGH =
  实验候选还是可验收 =

窗口：
  时间 =
  poll_mode =
  串口/恢复负责人 =
```

## 4. PC2 收到 P0 后会做什么

1. 只读 VERSION/STATUS，确认 host 映射；
2. RESET + 30 TEST session0；
3. session 0/1/2 + interleaved；
4. ACK_DONE、多帧、SOFT_RESET/FAULT 恢复；
5. 单层 Attention golden；
6. 30 层固定 token；
7. 之后才做 M 单 prompt 生成、batch3 和 B/M 对比。

在 P0 前，PC2 不写候选 CONTROL，不把当前 wire-only 结果当 resetfix/Attention 验收。
