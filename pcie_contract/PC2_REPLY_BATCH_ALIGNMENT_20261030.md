# PC2 回复 B：多序列 B/M 吞吐实验对齐

日期：2026-10-30
回复对象：B / FPGA 侧
状态：**PC2 对齐意见 + 当前证据；协议未冻结，未改 v2 contract，未生成多 session bit，未上多 session 板测**
相关：
- B：`BATCH_KV_LAYOUT.md`、`B_TO_PC2_BATCH_ALIGNMENT_20261030.md`
- PC2：`pcie_contract/MULTI_SESSION_INTERFACE.md`（v3 DRAFT）
- PC2：`docs/NPU_BATCH_CAPABILITY_20261030.md`

## C1 协议 / session / seq

**接受 B 的总体方向，但建议修正 session ID 与全局控制的编码：**

- `max_sessions = 3`，session ID **0/1/2** 对应 3 个 KV context；
- `seq` 仍是全局请求/响应匹配序号，**不复用为 session ID**；
- **全局 RESET / FAULT / CAPABILITY 使用 `session_id = 255 (0xFF)`**，不占用 0/1/2；
  - ATTENTION/TEST 只允许 0/1/2；
  - 3..254 首版非法；255 只允许 control op。
- 首版 **单帧在途**；多帧队列不在首版。
- header 仍 32B，`version=3`；session ID 放 v2 `padding0` 的第 1 字节（offset 9），其余 padding/reserved 为 0。
- payload 保持当前 1920B / 1152B；多 session 不加 batch payload。
- v2 帧一律拒绝；不做兼容猜测。

请 B 确认：
1. 0/1/2 与 255 control 是否便于 RTL 实现；
2. RESET 是否接受 `session_id=0xFF, layer=255, position=0`；
3. 若 B 更希望 session 1/2/3，请明确，PC2 改 wire 映射，但不要 0 同时表示 session0 和 global。

逐字节合法/非法样例和 hash 在双方确认上述编号后由 PC2 补齐。

## C2 CAPABILITY / BAR

**首版先不做 CAPABILITY 查询。** B 文档明确当前无此能力，PC2 不在旧 BAR 上猜偏移。

首版使用 **binding 静态值 + contract 版本**：

```text
protocol_version = 3
max_sessions = 3
MAX_T = 256
layers = 30
mode = B or M（由 bit/构建清单声明）
single_inflight = true
global_reset = true
```

- `session_stride`（B `0x005A0000`、M `0x001E0000`）属于 FPGA 地址图/构建清单，**不放进 wire header**；host 只发 session_id。
- 后续若 B 实现只读 CAPABILITY，PC2 再核对空闲 control/user 节点、BAR、offset、读取宽度、原子性；地址不预先指定。
- bit SHA256 继续由构建清单交接，不假定可从 BAR 读文件 hash。

## C3 RESET / FAULT / deadline

接受 B 的语义，PC2 侧要求：

1. 批开始：先确认 READY/无在途，再发全局 RESET（`session_id=0xFF`）；收到合法 ACK 后从各 session position=0 开始。
2. RESET 必须停止 dispatch、排空/安全终止在途 H2C/AXI/响应、清空全部 session 逻辑历史/next_pos/缓存/响应状态；不要求物理清零 DDR，但 reset 后旧数据不可见。
3. 任何 CRC/length/session/layer/position/seq/重复/失序/引擎/DDR 错误：**停止整批、FAULT、不返回成功、不静默重试/追 KV**。
4. DDR 可能已部分写入；恢复后重建该 session 状态，不假设硬件可回滚。
5. 保留 Plan B 的 recovery/deadline 口径；当前 `poll_mode=0`、`force_st_c2h_wb=0`；`poll_mode=1` 会丢 C2H completion，不能用于长 run。
6. 旧 C2H 帧必须由明确 reset/recovery 排空；旧响应不得当新请求完成。

PC2 需要 B 给出 RTL 的 RESET/FAULT/READY 精确顺序和状态字；当前没有可读多 session 状态字。

## C4 NPU batch 能力（PC2 已实测）

已在板卡 RK3576 上完成 **RKNN MatMul 生产 wrapper**（`_rknn_matmul_no_c_init_v10.py`）算子级实测：

- batch=2/3 被接受，A `[M,K]`、C `[M,N]`；
- 所有 SmolLM linear shape 均与单行 NPU 输出逐位一致；
- 实际 v38 的 **211 个 linear 权重**（30 层×7 + LM head）batch2/3：**211/211 exact**；
- NPU linear-only 折算：

| 项 | batch1 | batch2 | batch3 |
|---|---:|---:|---:|
| 每 token linear | 56.37 ms | 29.48 ms | 20.02 ms |
| linear-only tokens/s | 17.74 | 33.92 | 49.95 |
| 相对 batch1 | 1.00× | 1.91× | 2.82× |

- 这是一次 `rknn_matmul_run` 的 M=batch，不是 Python 循环。
- 当前 `RKNNLinearEngine` 仍硬编码 M=1；需要改为 batch 输入/输出。
- 实验版 `host/backends/rknn_matmul.py` 不可作为 batch 依据；生产代码用 no-C-init wrapper。
- LM head 576×49152 的 context setup 约 555 ms/context；211 context 的装载和 RK 内存另计。
- **边界**：这是 NPU-only，不是整机 tokens/s；没有 FPGA Attention/PCIe/多 session。

## C5 多序列输入 / 独立 golden

**尚未交付独立 golden，不把人工/板端自洽数据标成独立 golden。**

PC2 可立即准备：
- 2–3 条不同 prompt 的 tokenizer/token ID/manifest（可复用 v50 的 prompt 集）；
- 输入 1920B、输出 1152B 的逐帧 manifest 字段；
- PC1/B 参考的存放路径与 SHA256 规范。

仍需要 B/PC1 给出：
- 两条**不同序列**的独立 B/M QKV/attention golden；
- 覆盖 pos0/31/32/33/63/64、普通层与重要层；
- M 的 tail 驱逐前后及 group 边界 golden；
- 逐帧 session/layer/position/offset/hash。

B 目前只有 session0 与 PC1 完整 DDR golden 一致；session1 是人工变化输入，**不能当作两条独立序列 golden**。PC2 不会把 session1 自洽重放写成独立验收。

## C6 实验口径

接受 B 的两组实验：

1. **同 batch**：B/M 各自 batch=1/2/3（实际支持范围内）；
2. **同 KV 预算**：固定预算；示例 B=1 / M=3 = 5.625 MiB，明确标为“受限 KV 预算示意”，不是 256 MiB DDR 已满，也不是 M 的硬件最大 batch。

固定：
- SmolLM-135M、同 tokenizer/prompt 集/生成规则/sampling/NPU 路径/MAX_T=256；
- 主指标：所有成功请求实际输出 token 总数 / 统一墙钟窗口（含 prefill/排队）；
- 辅助：decode-only tokens/s、TTFT、TPOT p50/p95、完成时间、失败率、FPGA 周期、DDR 字节、PCIe 分段、RK 内存峰值；
- 预热后至少 3 次，B/M 交替顺序；
- 不把 forward/s、teacher-forcing 回放或 NPU linear-only 当真实生成 tokens/s；
- 自由生成分叉后不能把后续 logits 当同输入逐位对拍。

## C7 测试窗口 / 板卡 / 源码

- 当前板卡：`end0` down，`end1=192.168.138.101` 可用；串口 root 可用。
- 当前 bit：单 session M；`anlogic-sgdma` service active，`poll_mode=1`（不是 batch/长 run 配置）。
- NPU 驱动正常；`kvdev` 不在 `video` 组，RKNN 必须 `runuser ... -G video`。
- 多 session 实验必须先有 B 的多 session bit；在 bit 到位前 PC2 不做多 session H2C。
- 窗口按独占规则预约；JTAG 后完整 recovery；每次记录 bit SHA256、驱动、binding、commit、输入 hash、原始日志。
- PC2 host/transport 代码在 PC2 分支；PC1 host/golden 目前还没有合并到 PC2 可用的多序列版本，需要先交接。

## C8 计数器

接受 B 不单方指定 BAR。PC2 需要：

- 计数器读取节点（control/user）、BAR、offset、对齐、宽度；
- 快照/清零/跨时钟稳定读回语义；
- 计数器是否与测量窗口重叠、是否包含 DMA 等待；
- 读取时机：测量结束后读累计值，避免每 token 高频读 BAR。

在 B 提供前，PC2 不会在现有 BAR 上猜测地址；当前性能数据只来自 host 计时/NPU API。

## 需要 B 先交付

1. 确认 C1 的 0/1/2 + 0xFF control（或给替代）；
2. 多 session B/M bit、TD/P&R 资源/时序、bit SHA256、烧录记录；
3. endpoint/CDC/Plan B 的 RESET/FAULT/READY 精确顺序；
4. 两条独立序列的 B/M golden（或由 PC1 出）；
5. 计数器读回接口；
6. 若实现 CAPABILITY，给只读地址/字段/版本。

PC2 侧已完成：多 session 接口 v3 草案、NPU batch=2/3 算子级和全 211 权重实测。等 B 的 bit/协议确认后，PC2 接 codec/mock/板端链路和整机 tokens/s。
