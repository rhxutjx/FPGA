# PC2 v3 M experimental bit 板测记录（2026-10-31）

状态：**M 实验 bit 已上板；仅完成 RESET/TEST、状态/ACK、错误注入；未做 Attention 数值、KV 隔离、性能。**

## 1. 环境与 bit

| 项 | 值 |
|---|---|
| 板卡 | RK3576 EVB1，`192.168.137.101`（`end1` 不可达，改用 `end0`） |
| 内核 | Linux `linaro-alip` 6.1.99 aarch64 |
| 驱动 | `anlogic_pci`，`poll_mode=1`，`reset_on_close=Y`，h2c/c2h timeout 10s |
| 端点 | `0000:21:00.0 [1edb:abcd]`，BAR0 1M，BAR1 64K |
| bit | `v3_m_experimental.bit`，SHA256 `25654eacc03949f131330ed3eda0ea370f1ade9095a199a9a7bd1d1dc3379fe4` |
| VERSION | BAR0 `0xAC = 0x504C4233`（B 候选版本码） |
| 关键过程 | B 烧录后先 `pcie1-recover.sh` 重新枚举；每次新 host 进程前都需 recovery |

首次恢复前 BAR0 全 `0xffffffff`，`lspci` 仍显示 `1edb:abcd`（假 up）。执行串口 root：

```text
/usr/local/sbin/pcie1-recover.sh
```

后 BAR0 正常，`0xAC=0x504C4233`。

## 2. 只读状态

初始：

```text
BAR0 0xA4 STATUS = 0x00FF0010
  READY=1, FAULT=0, BUSY=0, DONE=0, RESET_BUSY=0, ERR=0
  FAULT_CODE=0, LAST_SESSION=255
BAR0 0xA8 CONTROL = 0x00000000
BAR0 0xAC VERSION = 0x504C4233
```

与 B 的“FAULT_CODE=0、LAST_SESSION=255”声明一致；host 不能依赖细 fault 定位。

## 3. RESET + TEST（通过）

命令（板端一个进程内完成，避免跨进程 C2H 失效）：

```sh
cd /home/kvdev/work_pc2_pcie/v3_smoke_20261031
python3 run_v3_smoke_on_board.py \
  --sessions 0,1,2 --rounds 30 --timeout-s 5 --ack-done \
  --out v3_smoke_30x3_20261031.json
```

结果：

- `RESET_CACHE`：H2C 32B，C2H 32B ACK，session=255/op/seq/CRC 全部通过。
- `TEST`：session 0/1/2 各 30 轮，共 **90/90 通过**。
- 每轮 C2H 1184B；回显 session/op/layer/position/seq 正确；payload 为 H2C 前 1152B。
- 每轮 `STATUS=0x00FF0001`：`DONE=1, ERR=0, FAULT=0`。
- 每轮写 `CONTROL.ACK_DONE=4` 后 `STATUS=0x00FF0010`：`READY=1`。
- `LAST_SESSION` 始终 `255`，与 B 当前实现一致；不影响 TEST 结果。

证据：`v3_smoke_30x3_20261031.json`（90 条 record，`SMOKE_OK`）。

追加 **interleaved** 测试（同一 recovery 进程）：

```sh
python3 run_v3_smoke_on_board.py --sessions 0,1,2 --rounds 10 --interleave \
  --timeout-s 5 --ack-done --out v3_smoke_interleave_10x3_20261031.json
```

结果：session 顺序 `0,1,2,0,1,2...`，**30/30 通过**，每轮 DONE=1/ERR=0，ACK_DONE 后 READY；`SMOKE_OK`。  
证据：`v3_smoke_interleave_10x3_20261031.json`。

## 4. 错误注入（通过）

每个 case 单独 recovery 后发送；只记录 FAULT，不做 SOFT_RESET：

| case | 发送 | STATUS | 解释 |
|---|---|---|---|
| `bad_crc` | TEST，CRC 翻转 | `0x00FF0026` | `FAULT=1, ERR=3` CRC |
| `invalid_session` | TEST session=3，CRC 正确 | `0x00FF0028` | `FAULT=1, ERR=4` SESSION |
| `nan` | RESET 后 ATTENTION，FP16 NaN | `0x00FF002A` | `FAULT=1, ERR=5` PROTOCOL |

- 未发现 C2H 成功响应；符合 fail-stop。
- `FAULT_CODE` 均为 0，`LAST_SESSION` 均为 255；只有粗 ERR 可用于分类。
- 非有限 QKV 在 RESET 后按 protocol 拒绝；不验证“是否写 KV 前拒绝”的内部时序。

证据：

- `v3_fault_bad_crc_20261031.json`
- `v3_fault_invalid_session_20261031.json`
- `v3_fault_nan_after_reset_20261031.json`

## 5. 发现的问题

### 5.1 CONTROL.SOFT_RESET 未恢复 FAULT

bad CRC 进入 FAULT 后，写 `BAR0 0xA8 = 1`（SOFT_RESET bit0），读回：

```text
STATUS = 0x00FF002E
  FAULT=1, ERR=7 (INTERNAL), READY=0
```

即 **SOFT_RESET 没有清除 FAULT**，反而进入 ERR=7；最后必须用串口 root `pcie1-recover.sh` 恢复。  
这与 B 的“FAULT 只在安全 SOFT_RESET 完成后清除”目标不一致；需要 B 检查控制位/soft reset 实现、写 mask、alias 和 reset 完成条件。  
`ACK_DONE=4` 在同一 `0xA8` 写入是有效的（TEST 90 轮全部清除 DONE），所以不是整个控制写路径失效；问题集中在 bit0 soft reset 或其内部安全条件。

B 2026-11-01 补充：`0xA8` 与 vendor RAM[42] alias，`0x000810A8` 可修改同一 RAM；该修复未进入 bit。PC2 本轮写入候选 `0xA8` 可能已触发 vendor RAM alias；后续停止访问候选 `0xA4/0xA8/0xAC/0xB0..0xBC`，也不据此改正式 binding。

### 5.2 跨 host 进程 C2H 不可复用

一个新 host 进程在上一进程退出后直接读 C2H 会得到：

```text
OSError: [Errno 512] Unknown error 512
```

必须先 `pcie1-recover.sh`。这与之前 v2 结论一致；v3 测试必须：

- 一个 recovery 窗口内只跑一个 host 进程；或
- host 保持同一进程/长驻，不反复 open/close C2H 进程边界；或
- B 修复 driver/engine 的 cross-process reuse。

本轮 90×TEST 和错误注入都遵守“一进程一 recovery”。

### 5.3 其他

- `pcie1-fpga.sh` 是 PERST# + rebind，不重新烧 FPGA；恢复不会覆盖 B 的 M bit。
- B 的 timing 是 setup WNS `+0.030 ns`、hold WNS `+0.009 ns`（正余量但很小）；仍有 HIGH clock 未清，本轮是实验性板测，不是签核结论。
- 未做 Attention 数值：没有两条独立真实 NPU prompt/golden；TEST 不验证 KV 内容。
- 未做 B bit；B 只烧了 M。

## 6. 当前板状态

最后执行 recovery，端点恢复 READY：

```text
BAR0 0xA4 = 0x00FF0010 (READY=1)
BAR0 0xAC = 0x504C4233
```

没有遗留 host 长驻进程；下一次测试前仍应先确认状态并重新 recovery。

## 7. 建议给 B

1. 修 `CONTROL.SOFT_RESET`：确认 bit0 写 mask、alias、reset 完成条件和 FAULT 清除；当前 bad CRC 后 soft reset 变 ERR=7。
2. 确认 `FAULT_CODE`/`LAST_SESSION` 是否实现；当前无法定位 fault 的 session/layer/position。
3. 修 cross-process C2H/DMA reuse，或明确 host 必须一进程一 recovery。
4. 给 B bit 和两条独立真实 NPU prompt 的逐层 QKV/golden；之后才能做 Attention/KV 隔离。
5. timing closure 前不要把本轮当签核/吞吐结论。
