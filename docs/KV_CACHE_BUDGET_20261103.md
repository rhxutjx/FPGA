# B/M KV Cache 预算整理（2026-11-03）

状态：**静态布局/预算数据，不是实测 DDR 占用或 DDR 流量。**  
当前没有经 BAR 验证的 DDR/Attention 计数器，不能把本页数字写成板端实测。

## 1. 模型与预算口径

- SmolLM-135M：30 层，hidden=576，KV dim=192（3 个 KV head × head_dim 64），MAX_T=256。
- B：FP16 KV。
- M：K3=14/18/26、V4=14/22/23，其他 K2/V2；group=32；recent FP16 tail=32。
- MAX_T 包含 prompt + 生成历史。
- 以下为固定 KV 区域预算，不含共享工作区、DDR 对齐、额外保留 slot。

## 2. 单 session

| 方案 | 单 session 预算 | 字节 |
|---|---:|---:|
| B FP16 KV | **5.625 MiB** | 5,898,240 |
| M mixed + tail | **1.875 MiB** | 1,966,080 |

- B：30 层 × (K 192 + V 192) × 2 B = **23,040 B/token**；×256 = 5,898,240 B。
- M：1,966,080 B / 256 = **7,680 B/token**。
- M 的 1.875 MiB 包含量化数据、metadata 和 recent FP16 tail；不是实测写入量。
- B/M 单 session 容量比：**3×**。

## 3. 多 session

| 方案 | 活跃 session | 合计 |
|---|---:|---:|
| B FP16 | 1 | **5.625 MiB** |
| B FP16 | 3 | **16.875 MiB** |
| M mixed | 1 | **1.875 MiB** |
| M mixed | 3 | **5.625 MiB** |

- 等 KV 预算对比：
  ```text
  B batch=1：1 × 5.625 = 5.625 MiB
  M batch=3：3 × 1.875 = 5.625 MiB
  ```
- 这个 5.625 MiB 是**活跃会话布局预算**，不是整块 256 MiB DDR 已满，也不是实测峰值。
- B bit 实际预留几个 slot 未确认；B batch=1 只表示当前活跃 1 个 session，不代表 bit 只保留 1 个 slot。

## 4. 和 FPGA DDR 总容量

- FPGA DDR：**256 MiB 名义容量**。
- 5.625 MiB ≈ **2.2%**。
- 16.875 MiB ≈ **6.6%**。
- 这些只是 KV 固定区域；实际 DDR 还包含 metadata、工作区、buffer、对齐和保留区，未测。

## 5. 每层/每 token

| 方案 | 每层每 token |
|---|---:|
| B FP16 | **768 B** |
| M mixed（平均） | **256 B** |

## 6. 数据边界

- **没有实测 DDR 占用**。
- **没有可信的 DDR 读写字节计数器**；B 的计数器仍为离线 RTL 候选，未经 BAR 读回。
- 不是 DDR 峰值带宽、不是 DDR 实际 footprint、不是端到端吞吐。
- B 的实际 slot 保留数、metadata/tail 对齐、临时 buffer 可能改变占用。
- M 的 1.875 MiB/session 是 B 提供的布局预算；需要 B 的 RTL/地址图和板端读回进一步核对。

## 7. 来源

- B：`BATCH_KV_LAYOUT.md`
- B：`B_TO_PC2_EQUAL_KV_BUDGET_TEST_20261101.md`
- PC2：`docs/PC2_PROGRESS_20261103.md`
- PC2：`pcie_contract/PC2_M_BATCH3_30ROUNDS_20261103.md`（性能，不是 DDR 预算）
