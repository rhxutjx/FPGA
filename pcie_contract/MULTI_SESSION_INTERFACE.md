# 多 session Attention wire 接口（v3 DRAFT，已按 B 2026-10-30 回复对齐）

日期：2026-10-30  
状态：**PC2 DRAFT，未冻结、未改 `contract.json`、未上板、未提交**  
范围：SmolLM-135M，30 层，H=576，KV=192，MAX_T=256；B/M 同一 wire 接口，单请求在途，全局 RESET。  
依据：B 的 `B_REPLY_PC2_BATCH_ALIGNMENT_20261030.md`、`BATCH_KV_LAYOUT.md`，以及 PC2 的 `contract_v3_session.json`。

> 本文件只定义逻辑接口和已生成的离线向量。B 的多 session bit、RESET/FAULT/READY 状态字、TD/P&R、计数器 BAR 读回均尚未交付；不能把本文当作已上板能力。

## 1. 已确认的首版范围

- `max_sessions = 3`，Attention/TEST 的合法 session 为 **0/1/2**。
- `3..254` 非法；`255` **只用于全局控制 RESET_CACHE**，不分配给任何 KV context。
- `seq` 只做请求/响应匹配，不是 session ID；首版 **单帧在途**（`max_inflight=1`）。
- 首版 **不做 CAPABILITY 查询**；host 使用静态 binding：`protocol_version=3`、`max_sessions=3`、`MAX_T=256`、30 层、固定 B/M。
- 全局 RESET，不做 per-session reset；FAULT 为 fail-stop，不静默重试。
- v3 与 v2 **不兼容**；新 bit 拒绝 v2，host 不猜测旧版本。
- B/M 只改变 bit 内部 KV 策略/布局；wire 帧相同。B stride `5,898,240 B`，M stride `1,966,080 B`（来自 B 的 `BATCH_KV_LAYOUT.md`，不进入 wire）。

## 2. 帧与 payload

保持 32 B header、magic `KVMX`、little-endian、CRC-32/ISO-HDLC；`version=3`。

| op | H2C payload | C2H payload | 说明 |
|---|---:|---:|---|
| ATTENTION=0 | 1920 B | 1152 B | 一帧只含一个 session 的当前 token Q/K/V |
| RESET_CACHE=1 | 0 B | 0 B | 全局 reset；`session_id=255`、`layer=255`、`position=0` |
| TEST=2 | 1920 B | 1152 B | 不执行 Attention、不改 KV；返回 H2C 前 1152 B |
| CAPABILITY=3 | — | — | **首版不实现、不定义、不占用 opcode** |

- H2C 总长 1952 B；C2H 总长 1184 B；RESET 为 32 B header。
- Attention/TEST 的 H2C 1920 B：Q 9×64、K 3×64、V 3×64，FP16 LE，head-major，`kv_head = q_head // 3`。
- 生产数值约定尚未最终验证；当前 golden 的“FP16 pattern”只用于 wire 测试，不等于模型质量验收。

## 3. v3 header（32 B）

| offset | size | field | 首版规则 |
|---:|---:|---|---|
| 0 | 4 | magic | `4B 56 4D 58`，u32 LE `0x584D564B` |
| 4 | 2 | version | **3**；v2/未知版本拒绝 |
| 6 | 1 | op | 0 attention / 1 reset / 2 test；3 保留且拒绝 |
| 7 | 1 | flags | 必须 0 |
| 8 | 1 | layer | attention/test 0..29；reset 255 |
| 9 | 1 | **session_id** | attention/test 0/1/2；reset 255；其余拒绝 |
| 10 | 2 | padding0 | 必须 0 |
| 12 | 4 | position | attention/test 0..255；reset 0 |
| 16 | 4 | seq | 非零 u32；每个请求递增；不兼作 session |
| 20 | 2 | payload_len | 方向相关的精确逻辑长度，不含 DMA padding |
| 22 | 2 | padding1 | 必须 0 |
| 24 | 4 | crc32 | header 的 crc 字段清零后 + 逻辑 payload |
| 28 | 4 | reserved | 必须 0 |

- CRC 覆盖 offset 9 的 session_id。
- C2H 必须回显 `session_id`、`op`、`layer`、`position`、`seq`；**不要求回显 payload_len**（Attention H2C 1920 / C2H 1152 不同）。C2H 自身的 payload_len 必须是对应方向的合法值。
- 旧 C2H、错 session、错 seq、错 layer/position、CRC/长度/方向/保留字节错误一律 fail-stop。

## 4. session 语义

- `session_id=0/1/2`：三个独立 KV 序列；每个 session 独立维护 history、每层 K/V、metadata、tail/迁移状态、valid/init 状态。
- 同一 session 的 `position` 从 0 开始连续递增；重复、跳号、未来位置、跨层乱序拒绝。
- 不同 session 的 `(layer, position)` 可以交错；一帧只作用于一个 session。
- RESET 是 **全局**：清除全部 session 的逻辑历史；不要求物理清零 DDR，但 reset ACK 后旧 KV 不可读。
- 首版没有 per-session reset；没有 session 换出/热替换；不实现 queue depth >1。
- 驻留 3 个 session 只表示容量/接口能力；吞吐收益必须实测，不能由驻留数推断。

### 4.1 首版 host 层顺序（B 2026-11-01 要求的具体例子）

endpoint 只检查每个 `(session,layer)` 内的 position 连续；**跨层顺序由 host 负责，endpoint 不宣称检测跨层乱序**。首版 host 采用：

```text
for each session independently:
    for p in 0 .. T-1:
        for layer in 0 .. 29:
            ATTENTION(session, layer, p)
        # 然后才进入 p+1
```

- 同一个 `(layer, p)` 下，host 可以交错不同 session 的请求。
- 这不是“先 layer0 所有 position、再 layer1”的另一种顺序；本版明确采用 **position p 的 layer0..29，再 p+1**。
- 该顺序是 host 调度契约；endpoint 不检查 layer 间依赖，也不能用它来证明跨层乱序被拒绝。

### 4.2 非有限 QKV

- Q/K/V 中 NaN 或 Inf：首版按 **protocol reject**，`FAULT=1, ERR=5`，不返回成功 C2H。
- `FAULT_CODE` 首版可为 0（未实现细分类），host 只看 `FAULT+ERR`。
- “在写 KV 前拒绝”是 B RTL 内部行为；PC2 只能验证外部无成功响应，不能从 wire 证明内部时序。
- PC2 M 板测在 RESET 后发送 Q=NaN 的 Attention，观察到 `STATUS=0x00FF002A`（FAULT=1, ERR=5）。

## 5. RESET / FAULT / READY 方向（B 的目标实现，待 RTL/板测确认）

B 已同意的接口方向：

```text
batch start -> READY -> 全局 RESET -> RESET ACK -> position=0 开始
```

B 的目标行为：

1. RESET 帧只在确认无在途请求时发送；接收并校验后阻止新 dispatch，等待现有 guard/FIFO/engine/AXI 安全排空。
2. 清除所有 `(session, layer)` 的 endpoint history、M store `next_pos`、读写缓存 valid 标志和相关响应状态。
3. 只有完成上述条件才返回 RESET ACK；之后才允许 READY。
4. 非法帧、失序、engine/DDR 错误后停止整批，不返回成功；不承诺撤销已写 DDR。按 Plan B recovery 排空 C2H 并全局 RESET，重新创建批次；禁止未经确认重试追加。

**PC2 最新逻辑状态基线见 `PLAN_B_STATUS_V3.md` / `plan_b_status_v3.json` / `plan_b_status_v3.py`：STATUS 的 DONE/ERR/READY/FAULT/BUSY/RESET_BUSY/FAULT_CODE/LAST_SESSION，CONTROL 的 SOFT_RESET/ABORT_BATCH/ACK_DONE，以及启动、每帧、fault recovery 序列。具体地址、读写节点、READY/ACK/DONE/传输完成的精确时序、busy 时复位策略仍未绑定；B 必须对照新 RTL 逐项确认后才能生成可验证 bit。**

## 6. 错误与恢复

以下任一情况进入 FAULT，停止整批：

- v2/未知 version、未知 op、op=3；
- session 3..254、Attention/TEST 使用 255、RESET 不用 255；
- layer/position 越界、同 session 重复/跳号/未来 position；
- 旧/错 session/错 seq C2H、错 layer/position；
- CRC、长度、方向、flags、padding、reserved 错误；
- C2H 超时、短读写、driver/transport 错误。

FAULT 后不自动重试、不自动重发 KV；显式 recovery（现有 poll_mode=0 流程）、全局 RESET、隔离旧响应/旧队列；恢复后的第一帧不能当作故障请求的结果。

## 7. 已生成的离线交付（DRAFT）

- `contract_v3_session.json`：机器可读 contract；session 0..2，control 255，`max_sessions=3`，`max_inflight=1`，B/M stride，CRC/header 布局，无 CAPABILITY。
- `multisession_v3.py`：独立 v3 codec；不改 v2 `contract.py`。
- `golden_vectors_v3.json`：12 个正例（RESET/ATTENTION/TEST，session 0/1/2，边界 layer29/pos255）+ 13 个负例（v2、session 3、session 255 用于 Attention、RESET session0/layer0、flags、padding、reserved、payload_len、seq0、坏 CRC、短帧、响应 seq 不匹配）；每帧含 hex 和 SHA256。
- `make_multisession_v3_vectors.py`：可复现生成器。
- `test_multisession_v3.py`：15 项离线测试，当前全部通过；只证明 codec/向量，不证明 FPGA。
- `PLAN_B_STATUS_V3.md`：Plan B 最新逻辑状态定义（STATUS/CONTROL 位图、全局状态机、RESET/FAULT/READY 序列、超时和恢复）。
- `plan_b_status_v3.json`：机器可读状态/控制位定义；`status_offset`/`control_offset` 明确为 `null`/UNBOUND，不猜地址。
- `plan_b_status_v3.py` + `test_plan_b_status_v3.py`：32-bit 状态/控制位编解码和不变量测试，当前 15 项通过；不证明 RTL。

> `golden_vectors_v3.json` 中标记为 protocol-test 的 C2H payload 是确定性测试 pattern，**不是板端 Attention/KV 输出**；TEST 的 C2H 才是 H2C 前 1152 B。

## 8. 测试矩阵

### 8.1 codec/mock（已做）

- v3 RESET/ATTENTION/TEST 编解码与 CRC；
- v2、未知版本、op=3 拒绝；
- session 3/254/255 用于 Attention 拒绝；RESET 非 255 拒绝；
- layer/position 边界；flags/padding/reserved 非零拒绝；
- 坏 CRC、错 payload_len、短帧拒绝；
- C2H 回显匹配；响应 seq 不匹配拒绝。

### 8.2 多 session 隔离（等 B bit）

- 两个不同 session 交替 layer/position，输出分别匹配各自独立 golden；
- 每 session position 重复/跳号/未来位置拒绝；
- 全局 reset 后旧 KV 不可读；
- tail 驱逐（pos31/32/33/63/64）在各自 session 内正确；
- 重要层/普通层交错、背压、整批 fault/recovery；
- B/M 各自 session 输入和输出 golden。

### 8.3 吞吐（不混入正确性）

- batch=1/2/3；固定 T=256；同 prompt/生成/采样/计时边界；预热后至少 3 次；
- 报告真实输出 tokens/s、TTFT、TPOT p50/p95、错误率；同时报告 NPU linear-only、FPGA、PCIe、调度分解；
- B=1/M=3 的 5.625 MiB 是受控 KV 预算示例，不表示 DDR 已满或硬件最大 batch；
- 不把 NPU linear-only 或 teacher-forcing forward/s 写成真实端到端 tokens/s。

## 9. 计数器/控制节点建议（待 B 确认，不占用现有地址）

B 目前只有离线 RTL 计数器，尚未经 BAR 读回。PC2 建议：

- 使用现有已加载的 **user 控制字符设备**做 32-bit `pread`/`pwrite`，不默认 raw mmap，不新造驱动；
- 在 B 确认空闲的 BAR0 窗口放一个只读快照块，候选（**仅建议，未确认**）：
  - `+0xB0` COUNTER_SELECT (W)；
  - `+0xB4` COUNTER_VALUE_LO (R)；
  - `+0xB8` COUNTER_VALUE_HI (R)；
  - `+0xBC` COUNTER_SNAPSHOT (W1) / STATUS (R)。
- 计数器至少：attention_frames、h2c_bytes、c2h_bytes、ddr_read_bytes、ddr_write_bytes、busy_cycles、fault_count；64-bit 用 snapshot 后两次读保证一致。
- B 必须先确认 offset 空闲、跨域稳定性、读写语义和 reset 行为；确认前 PC2 不使用这些地址，也不把它们写入正式 contract。

## 10. 仍缺的交付/阻塞

1. B 的多 session v3 bit、B/M bit hash、TD/P&R 资源与时序、烧录记录。
2. B 对 `PLAN_B_STATUS_V3.md` 的 STATUS/CONTROL offset、节点、读写 API、READY/ACK/DONE/RESET_BUSY 时序、fault 快照和 busy reset 行为逐项确认；当前仍为 PC2 DRAFT/UNBOUND。
3. 两条**独立 prompt** 的逐层逐位 Q/K/V 输入、token ID、量化/tokenizer hash、顺序和每帧 hash；B 目前 session1 是人工变化输入，不是独立 golden。
4. PC1 的 host 多序列调度/golden；当前 `RKNNLinearEngine` 仍硬编码 M=1。
5. 计数器 BAR 读回；当前只有离线 RTL 候选。
6. 板卡 `end0` down，使用 `end1=192.168.138.101`；`kvdev` 无 `video` 组，RKNN 需 `runuser -G video`；`anlogic-sgdma` 当前 `poll_mode=1`，长跑前切 `poll_mode=0`。

在这些到位前，只能做 codec/mock/NPU 离线验证，不能声称多 session 整机 tokens/s。
