# 给 B：PC2 联调前需要你提供/确认的清单

日期：2026-11-02  
状态：PC2 已收到 B 的 M resetfix `.bit` 和构建报告；板上能跑 wire-only 单帧 RESET/TEST，但 host 寄存器映射未确认，不能继续 ACK_DONE/多帧/SOFT_RESET。  
原则：**没有确认的 BAR 映射，PC2 不写候选 CONTROL，不猜地址。**

## 0. 一句话结论

现在缺的不是“再烧一次”，而是 **把板上 bit 和 host 可见的 STATUS/CONTROL/VERSION 绑定起来**，并给出可复现的烧录/时序/测试记录。B 把下面 **P0** 填完，PC2 就可以继续板测。

## 1. P0：不提供就无法继续

### 1.1 当前板上到底是哪一版

请确认并给出：

| 项 | 请填 |
|---|---|
| 模式 | B / M |
| 完整文件路径 | |
| 完整 SHA256 | |
| 烧录时间/操作者 | |
| JTAG 还是 Flash | |
| 烧录后是否执行 `pcie1-recover.sh` | |
| 当前板上实际读到的 VERSION | |
| 当前板上实际读到的 STATUS | |
| 已知可回退 bit | |

已给出的 resetfix 候选：

```text
B: E:\KVmix\batch_v3_b_resetfix_20261101\v3_b_experimental.bit
   D24B109D6E61CD180CBEB763F44F0E29393632521C8739BDC1C55B6A2F2F52AB
M: E:\KVmix\batch_v3_m_resetfix_20261101\v3_m_experimental.bit
   8291B81385E3705D3B8887EE9DA544712BC55F598992AB0AB53737800035AAE4
```

请明确当前烧的是这两个之一，还是更新的 build。

### 1.2 主机 BAR → 内部 AXI-Lite 的真实映射

B 文档现在只给了内部候选：

```text
STATUS  0x000800A4
CONTROL 0x000800A8
VERSION 0x000800AC
```

请给**实际主机访问表**，不要只说“内部地址”：

| 主机路径 | 主机 offset | 内部地址 | 读/写 | 位宽 | WSTRB/mask | 副作用/alias |
|---|---:|---|---|---|---|---|
| BAR0 或 BAR1 | `0x____` | `0x000800A4` | R | 32-bit | | |
| BAR0 或 BAR1 | `0x____` | `0x000800A8` | W | 32-bit | `0xF`? | |
| BAR0 或 BAR1 | `0x____` | `0x000800AC` | R | 32-bit | | |

还需要：

- 访问节点/API：`control` ioctl、`user` pread/pwrite、还是其他；
- 地址是否加 `0x80000` 基址；
- 高地址/vendor bank alias 是否仍在；
- 读是否有副作用；
- 写非法值/组合位的准确行为；
- 是否必须完整 32-bit 写。

**注意：** PC2 已实测 host `0xA4/0xAC=0`，`0xA8/0x800A8` 表现为 vendor RAM alias；这些结果不能证明 RTL 错，只说明 host 候选映射未生效。

### 1.3 resetfix 到底修了什么、怎么判定通过

请给一段可执行的验收序列和期望值：

```text
RESET_CACHE -> TEST -> 坏 CRC -> FAULT
-> CONTROL.SOFT_RESET -> READY
-> RESET_CACHE -> TEST
```

请明确：

- `SOFT_RESET` 的合法写值/bit；
- 写后先看 `RESET_BUSY` 还是直接 `READY`；
- `FAULT`/`ERR` 的清除条件；
- 期望 `FAULT_CODE`/`LAST_SESSION`（当前为 0/255 还是已实现）；
- 真实 DDR 掉线与应用复位如何区分；
- 失败时保留哪些状态/日志。

### 1.4 测试窗口与恢复

| 项 | 请填 |
|---|---|
| 独占窗口时间 | |
| 谁负责烧录/恢复 | |
| 串口 root 是否可用 | |
| `poll_mode` 用 0 还是 1 | |
| 回退 bit/恢复命令 | |
| 失败后谁处理 | |

## 2. P1：能测但会影响结论

### 2.1 时序/CDC 签核状态

请明确：

- B/M 最终 setup/hold WNS；
- STA coverage；
- no-clock / dummy-node / PLL-clock-buffer HIGH 是否接受；
- CDC/异步 FIFO/复位是否签核；
- 这是“实验候选”还是“可验收版”。

已知：M resetfix `+0.069/+0.012 ns`，STA 99.50%；B `+0.073/+0.020 ns`；均有 HIGH，不能称签核。

### 2.2 B bit

PC2 目前只有 M 板测；要做 B/M 对比，请给 B bit 的同一套信息：

- 文件/hash/烧录记录；
- host 映射；
- RESET/TEST/FAULT/soft reset 证据；
- 与 M 相同的测试序列。

### 2.3 独立 golden / M closed-loop

PC2 已提供 3 条独立 prompt 的 QKV（3150 帧）：实际 RK NPU post-RoPE + CPU F32 attention 反馈，**不是 M closed-loop**。

请 B 给：

- 同 3 条 prompt 的 M Attention 输出 golden（session/layer/position 顺序、hash、策略）；
- 或明确接受 PC2 用 M bit 重新采集 closed-loop QKV；
- 以及 goldens 的独立生成方式/源码版本。

### 2.4 计数器

如果要用 DDR/Attention 计数，请给：

- BAR/offset、快照语义、64-bit 读法、reset 行为；
- 是否在 resetfix bit 中实现。

当前 `0xB0..0xBC` 未确认，PC2 不访问。

## 3. 当前 PC2 侧状态

- M bit 文件 hash `8291...` 已校验；
- v3 wire-only 单帧 RESET/TEST 通过；
- host `0xA4/0xAC=0`，`0xA8/0x800A8` 仍为 vendor RAM alias；
- ACK_DONE、多帧、多 session、SOFT_RESET 未通过（因为 host 映射未确认，不一定是 RTL 失败）；
- 已跑 38 项离线测试 + 3150 帧 mock batch replay；
- 已生成 3 prompt QKV/batch3 调度，但仍不是 M golden。

## 4. 请 B 直接回复的模板

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
  RESET/TEST/坏 CRC/FAULT/SOFT_RESET 的期望序列 =
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

PC2 收到 P0 后，先只读 VERSION/STATUS，再按双方窗口做 RESET/TEST、ACK_DONE、多 session、SOFT_RESET；在 P0 前不写候选 CONTROL。
