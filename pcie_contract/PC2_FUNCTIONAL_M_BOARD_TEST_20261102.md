# PC2 板测：M functional BAR 版（2026-11-02）

状态：**RESET/TEST、多 session、FAULT/SOFT_RESET、70 帧 layer14 golden 通过。**  
未做：完整 M 生成、三条 prompt M closed-loop、B bit、性能/端到端 tokens/s。

## 1. bit

B 文件：

```text
E:\KVmix\batch_v3_m_bar_functional_20261102\v3_m_experimental.bit
SHA256 3BC476B360470EBB8126B6509372C20AD1518EC2E8BC1633F489A5CB0BF87A8D
```

B 尚未给功能版板上 JTAG 记录；PC2 无法从 FPGA 回读 bitstream hash。  
当前 host 读到 `VERSION=0x504C4233`，不是诊断版 `0x504C4433`，确认板上不是 diagnostic bit。

## 2. 只读（recovery 后）

```text
BAR0 0xAC    = 0x504C4233
BAR0 0xA4    = 0x00FF0010
BAR0 0x800AC = 0x504C4233
BAR0 0x800A4 = 0x00FF0010
BAR0 0x5C    = 0x56440013
BAR0 0xA8    = 0
```

- `BAR0 0xAC/0xA4` 和 `0x800AC/0x800A4` 都映射成功；
- 与诊断版得到的 AXI 窗口 `0x212000xx / 0x212800xx` 一致；
- 只读核对 **通过**。

## 3. RESET/TEST 多 session

### 3.1 session 0/1/2 各 30 轮

- RESET 32B ACK 通过；
- TEST **90/90 通过**；
- 每轮 DONE=1/ERR=0，ACK_DONE 后 READY；
- `v3_functional_smoke_30x3_20261102.json`。

### 3.2 interleaved 0/1/2 × 10 轮

- **30/30 通过**；
- session echo/route 正确；
- `v3_functional_interleave_10x3_20261102.json`。

## 4. FAULT / SOFT_RESET / resetfix

- 坏 CRC：`FAULT=1, ERR=3`；
- 非法 session：`FAULT=1, ERR=4`；
- RESET 后 NaN Attention：`FAULT=1, ERR=5`；
- 每个 case 后写 `CONTROL 0xA8=1`：
  - `STATUS` 回到 `0x00FF0010`（READY）；
  - 再 RESET + TEST 通过；
- 结果：**FAULT_RECOVERY_OK**；
- 说明 functional bit 的 SOFT_RESET 修复在本轮板测生效。

## 5. B 的 70 帧 layer14 golden

- `GOLDEN_70_OK`，70/70 帧通过；
- 包括 RESET、layer14 session0/1 pos0..32 交错、再次 RESET 后重放 pos0；
- 逐帧校验 v3 header/CRC、session/layer/position、1152B payload；
- 每帧与 B golden 的 expected payload 一致；
- `v3_golden70_20261102.json`。

边界：这仍是 B 说明的 **layer14 单层** golden；session0 是 PC1 v48 真实 NPU QKV，session1 是符号翻转合成输入；**不是三条 prompt 的 M closed-loop golden**，也不是完整 30 层/M 生成。

## 6. 当前板状态

- 最后一次 golden 后已 recovery；
- 端点/节点正常，无遗留 host 进程；
- 未写正式 binding，未改 bit。

## 7. 仍需

1. 完整 30 层 fixed-token 对拍；
2. 三条 prompt 的 M closed-loop QKV/golden；
3. 完整 M 生成；
4. B bit 对比；
5. batch3/NPU 行堆叠和性能；
6. B 的 timing/CDC 签核。

## 8. 证据

```text
docs/evidence/v3_functional_bar_20261102/v3_functional_smoke_30x3_20261102.json
docs/evidence/v3_functional_bar_20261102/v3_functional_interleave_10x3_20261102.json
docs/evidence/v3_functional_bar_20261102/v3_functional_fault_recovery_20261102.json
docs/evidence/v3_functional_bar_20261102/v3_golden70_20261102.json
```
