# PC2 板测：B v3 M experimental bit（2026-10-31）

状态：**M 实验 bit 已由 B 烧录；PC2 完成 RESET/TEST、STATUS/ACK、错误注入。未做 Attention 数值、KV 隔离、B bit 或性能。**

## 1. 环境/版本

- 板卡 `192.168.137.101`，RK3576 EVB1，Linux 6.1.99。
- `21:00.0 [1edb:abcd]`；`anlogic_pci` `poll_mode=1`，`reset_on_close=Y`。
- M bit SHA256：`25654eacc03949f131330ed3eda0ea370f1ade9095a199a9a7bd1d1dc3379fe4`。
- `BAR0 0xAC VERSION = 0x504C4233`。
- 烧后先 `pcie1-recover.sh`；否则 BAR0 全 `0xffffffff`（假 up）。

## 2. 通过项

### 2.1 RESET + TEST

- 全局 RESET：32B H2C → 32B C2H ACK，session=255/op/seq/CRC 通过。
- session 0/1/2 各 30 轮 TEST：**90/90 通过**。
- 回显 session/op/layer/position/seq 正确；payload = H2C 前 1152B。
- 每轮 `STATUS=0x00FF0001`（DONE=1, ERR=0）；`ACK_DONE` 后 `0x00FF0010`（READY=1）。
- interleaved 顺序 `0,1,2,0,1,2...` 10 轮 × 3 session：**30/30 通过**。

### 2.2 错误注入

| case | STATUS | 结果 |
|---|---|---|
| 坏 CRC | `0x00FF0026` | `FAULT=1, ERR=3` |
| session=3 | `0x00FF0028` | `FAULT=1, ERR=4` |
| RESET 后 NaN Attention | `0x00FF002A` | `FAULT=1, ERR=5` |

- 错误时没有成功 C2H；符合 fail-stop。
- `FAULT_CODE=0`、`LAST_SESSION=255`；只有粗 `ERR` 可用。

## 3. 发现的问题

### 3.1 SOFT_RESET 未恢复 FAULT

坏 CRC 后写 `BAR0 0xA8 = 1`（SOFT_RESET bit0），STATUS 变成：

```text
0x00FF002E  (FAULT=1, ERR=7 INTERNAL, READY=0)
```

没有清除 FAULT；必须用串口 root `pcie1-recover.sh` 恢复。  
同一 `0xA8` 写 `ACK_DONE=4` 是有效的（90+30 次全部清 DONE），所以不是整个控制写路径失效；请 B 检查 bit0 的写 mask、alias、reset 完成条件/FAULT 清除。

B 2026-11-01 补充：`0xA8` 与 vendor RAM[42] 存在 alias，`0x000810A8` 可修改同一 RAM；该修复尚未进入 bit。PC2 本轮写入候选 `0xA8` 可能已触发 vendor RAM alias；后续不再访问候选 `0xA4/0xA8/0xAC/0xB0..0xBC`，也不据此改正式 binding。

### 3.2 跨 host 进程 C2H 仍需 recovery

一个 host 进程退出后，新进程直接读 C2H 得到 `OSError: [Errno 512]`；必须重新 `pcie1-recover.sh`，或保持长驻进程。本轮每次测试都遵守“一进程一 recovery”。

### 3.3 其它

- B timing 是 setup WNS `+0.030 ns`、hold WNS `+0.009 ns`（正余量但很小）；HIGH clock 未清，本轮只算实验板测。
- 未做 Attention 数值：没有两条独立真实 NPU prompt/golden；TEST 不验证 KV 内容。
- 未测 B bit；B 只烧 M。
- B 的 `pcie1-fpga.sh` 不重烧 FPGA；recovery 不覆盖 M bit。

## 4. 证据

- `docs/evidence/v3_bits_20261031/BOARD_TEST_20261031.md`
- `v3_smoke_30x3_20261031.json`：90/90。
- `v3_smoke_interleave_10x3_20261031.json`：30/30 interleaved。
- `v3_fault_bad_crc_20261031.json`、`v3_fault_invalid_session_20261031.json`、`v3_fault_nan_after_reset_20261031.json`。
- 工具：`pcie_transport/tools/run_v3_smoke_on_board.py`、`run_v3_fault_on_board.py`、`read_v3_candidate_regs.py`。

## 5. 请 B 处理

1. 修 `CONTROL.SOFT_RESET`：当前 FAULT 后写 bit0 变 ERR=7，不能恢复。
2. 明确 `FAULT_CODE`/`LAST_SESSION`；当前 0/255，fault 无法定位 session/layer/position。
3. 修 cross-process C2H/DMA reuse，或明确 host 必须一进程一 recovery。
4. 给 B bit；timing closure；两条独立真实 NPU prompt 的逐层 QKV/golden。
5. 以上完成后再做 Attention/KV 隔离和吞吐；本轮不构成性能或最终验收结论。
