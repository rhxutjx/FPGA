# PC2 交给 B：v3 完整草案、逐字节向量、Plan B 状态（2026-10-30）

状态：**DRAFT，未冻结、未上板、未改 v2**。本文只列 PC2 已生成的文件和 B 需要确认/实现的项目；不表示多 session bit 已存在。

## 1. 交付文件（路径均在 `pcie_contract/`）

| 文件 | 内容 |
|---|---|
| `MULTI_SESSION_INTERFACE.md` | 完整 v3 逻辑接口：session 0/1/2、control 255、单帧在途、全局 RESET、无 CAPABILITY、B/M stride、错误/恢复边界 |
| `contract_v3_session.json` | 机器可读 v3 contract：header/offset、session 规则、CRC、payload、静态 binding、B/M stride、Plan B control-plane 指针 |
| `multisession_v3.py` | 独立 v3 codec；不改 v2 `contract.py`；`session_id` 在 offset 9；CRC-32/ISO-HDLC |
| `golden_vectors_v3.json` | **12 个正例 + 13 个负例**，每帧精确 `hex` + `sha256`；含 RESET/ATTENTION/TEST、session 0/1/2、layer29/pos255、v2、非法 session、坏 CRC、错长度、错 padding、响应 seq 不匹配 |
| `make_multisession_v3_vectors.py` | 可复现向量生成器 |
| `test_multisession_v3.py` | 15 项离线 codec/向量测试 |
| `PLAN_B_STATUS_V3.md` | Plan B 最新逻辑状态基线：STATUS/CONTROL 位图、全局状态机、启动/每帧/RESET/FAULT 序列 |
| `plan_b_status_v3.json` | 机器可读 STATUS/CONTROL 位定义；`status_offset`/`control_offset` 明确为 **null / UNBOUND** |
| `plan_b_status_v3.py` + `test_plan_b_status_v3.py` | 32-bit 状态/控制编解码、不变量和恢复序列测试 |
| `V3_DRAFT_MANIFEST.json` | 上述文件的大小与 SHA256；`board_verified=false` |

离线测试：**30 passed**（`test_multisession_v3` 15 + `test_plan_b_status_v3` 15）。只证明 codec/位定义，不证明 RTL、bit 或板端。

## 2. v3 已定的点

- `max_sessions=3`；Attention/TEST 合法 session **0/1/2**；`3..254` 非法；`255` 只用于 RESET_CACHE。
- RESET：`session_id=255`、`layer=255`、`position=0`、空 payload、32B ACK；全局清除所有 session 逻辑历史，不要求物理清零 DDR。
- 首版 **单帧在途**、**全局 RESET**、**无 CAPABILITY opcode**；host 静态 binding `protocol_version=3 / max_sessions=3 / MAX_T=256`。
- `version=3`，session_id 在 header offset 9，`padding0` 为 2B 零；v2 帧拒绝。
- C2H 回显 `session_id/op/layer/position/seq`；不回显 `payload_len`（Attention H2C 1920 / C2H 1152 不同）。
- B stride `5,898,240 B`，M stride `1,966,080 B`；不在 wire 中暴露地址。
- `golden_vectors_v3.json` 中标记 protocol-test 的 C2H payload 是测试 pattern，不是板端 Attention/KV 输出；TEST 的 C2H 是 H2C 前 1152B。

## 3. Plan B 最新逻辑状态（需要 B 对照 RTL 确认）

### STATUS（32-bit，只读，无 read-clear）

| bit | 名称 | 含义 |
|---:|---|---|
| 0 | DONE | Attention/TEST 的 C2H 稳定；保持到 `ACK_DONE` |
| 3:1 | ERR | 0 OK / 1 SEQ / 2 LAYER / 3 CRC / 4 SESSION / 5 PROTOCOL / 6 PAYLOAD_LEN / 7 INTERNAL |
| 4 | READY | 可接收新 H2C；仅当 BUSY=0、DONE=0、FAULT=0、RESET_BUSY=0 |
| 5 | FAULT | 粘滞 fail-stop；只有 SOFT_RESET 清除 |
| 6 | BUSY | 已接收一帧，处理中 |
| 7 | RESET_BUSY | 控制面 SOFT_RESET 或带内 RESET_CACHE 进行中 |
| 15:8 | FAULT_CODE | 细错误码（SEQ/LAYER/CRC/SESSION/VERSION/OP/PAYLOAD/FLAGS/PADDING/DDR/ENGINE/TIMEOUT/RESET） |
| 23:16 | LAST_SESSION | 最近完成/故障帧 session；首版可选 |
| 31:24 | reserved | 0 |

### CONTROL（32-bit，只写，self-clearing）

| bit | 名称 | 含义 |
|---:|---|---|
| 0 | SOFT_RESET | 应用逻辑复位，清 FAULT；不重置 PCIe HIP/BAR/link；完成后 READY=1；**不能替代**带内 RESET_CACHE |
| 1 | ABORT_BATCH | 可选；停止当前批进入 FAULT；没有 per-session abort |
| 2 | ACK_DONE | host 消费/校验 C2H 后清 DONE；只允许 DONE=1 时写 |
| 31:3 | reserved | 0 |

状态机（全局，无 per-session 状态）：

```text
UNINIT -> READY
READY --H2C ATTENTION/TEST accepted--> BUSY
BUSY --C2H stable, ERR=0--> DONE --ACK_DONE--> READY
BUSY --error--> FAULT --SOFT_RESET--> RESET_BUSY --reset complete--> READY
READY --RESET_CACHE accepted--> RESET_BUSY --32B ACK stable--> READY
```

启动/恢复：

```text
读 STATUS(x2) -> 若 FAULT/非 READY: SOFT_RESET + bounded poll READY
-> 带内 RESET_CACHE (255/255/0, seq) -> 读 32B ACK 校验
-> 从 position=0 开始；任何 reset 都创建新 batch
FAULT: 停 dispatch -> drain/隔离 C2H -> SOFT_RESET -> poll -> RESET_CACHE
       若不能恢复: root pcie1-recover.sh；auto_retry=false/auto_resend=false
```

**地址未绑定**：PC2 不猜 `STATUS`/`CONTROL` 的 BAR offset 或节点。B 需要给出真实 offset、读写 API、跨域同步、busy 时 SOFT_RESET 策略，以及 RESET ACK 与 READY 的精确顺序。

## 4. 请 B 确认/实现

1. `STATUS`/`CONTROL` 的物理 offset、节点、读写 API；是否沿用现有 Plan B 寄存器，需逐项对照。
2. `DONE` 用显式 `ACK_DONE` 清除是否可实现；若不能，给出等价的单帧完成/清除语义，**不能靠读 C2H 隐式清**。
3. `RESET_BUSY`、32B RESET ACK、`READY=1` 的先后；ACK 是否在 READY 前置稳定。
4. `FAULT_CODE`/`LAST_SESSION` 首版是否实现；若不实现，fault 如何定位 session/layer/position。
5. 计数器候选 offset `0xB0/0xB4/0xB8/0xBC` 是否空闲；64-bit snapshot 是否 atomic。未确认前 PC2 不使用。
6. 多 session v3 bit、B/M bit hash、TD/P&R、复位/时序验证；生成 bit 后按 `golden_vectors_v3.json` 和 `PLAN_B_STATUS_V3.md` 回归。

## 5. 仍未交付/阻塞

- B 的多 session v3 bit、B/M bit、TD/P&R、烧录与时序记录。
- 两条**独立 prompt** 的逐层 Q/K/V 输入、token ID、量化/tokenizer hash、顺序和每帧 hash；B 当前 session1 是人工变化输入，不是独立 golden。此项不阻塞 endpoint 集成，但阻塞最终多 session golden 验收。
- PC1 host 多序列调度/golden；当前 `RKNNLinearEngine` 仍 M=1。
- 计数器 BAR 读回；当前只有离线候选。
- 板卡 `end0` down，用 `end1=192.168.138.101`；`kvdev` 无 `video` 组，RKNN 需 `runuser -G video`；`anlogic-sgdma` 当前 `poll_mode=1`，长跑前切 `poll_mode=0`。

## 6. NPU 证据

- 报告：`docs/NPU_BATCH_CAPABILITY_20261030.md`
- 原始机器汇总与脚本：`docs/evidence/npu_batch_20261030/`
- 211 个实际 v38 权重 batch2/3 逐位 `211/211 exact`；NPU linear-only `17.74/33.92/49.95` tokens/s。
- 边界：不包含 FPGA Attention、PCIe、host 调度和真实生成；不是端到端 tokens/s。
