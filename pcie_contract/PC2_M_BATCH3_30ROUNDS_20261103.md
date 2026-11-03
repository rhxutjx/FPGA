# PC2 M NPU batch=3：3 预热 + 30 轮结果（2026-11-03）

状态：**PASS_M_BATCH3_30ROUNDS**  
模式：M-only；三条 prompt 同 batch=3；Attention 仍单帧在途、逐请求；不是 B/M 对比，也不是三路 Attention 并行。

## 1. 口径

- 三条 prompt：Tim / Spot / Mia；
- 每轮三条同时 batch=3，每 prompt 最多 8-token greedy；
- 每轮全局 RESET，新会话；
- 3 轮预热，不计入统计；
- 30 轮正式测量；
- 计时含 RESET、prefill、NPU、PCIe、FPGA Attention、host 调度；不含模型加载/context 创建；
- init（NPU contexts）：5.844 s，不计入 30 轮总墙钟。

## 2. 结果

| 项 | 值 |
|---|---:|
| 正式轮数 | 30 |
| 每轮 tokens | 24 |
| 总 tokens | 720 |
| 总墙钟 | 3492.032 s |
| aggregate | **0.20618 output tokens/s** |
| mean/轮 | 116.401 s |
| p50 | 116.299 s |
| p95 | 117.068 s |
| min | 115.317 s |
| max | 117.756 s |

- 30/30 成功，无失败、无 EOS 提前停止。
- 三条输出每轮一致：
  - Tim: `" look nice.\"\nHe took the truck"`
  - Spot: `" use it to make funny sounds. But"`
  - Mia: `" box of food. \"What's that"`

## 3. 对比

| 方案 | 墙钟/轮 | output tok/s |
|---|---:|---:|
| 三单 session 顺序 | ~140.803 s | 0.17045 |
| 三 session host 交错 | ~162.390 s | 0.14779 |
| **M NPU batch=3** | **116.401 s** | **0.20618** |

相对顺序：

- 墙钟快约 **17.3%**
- 吞吐高约 **21.0%**

相对 host 交错：

- 吞吐高约 **39.5%**

## 4. 边界

- 这是 **M-only**；没有 B bit，不能做正式 B/M 对比。
- batch=3 只批量化 NPU linear；Attention 仍单帧在途、逐请求。
- 没有独立 full-model M golden；输出一致只覆盖这三条固定 prompt。
- 0.206 tok/s 是 8-token 短生成、每轮 3 prompts，含 RESET；不是纯 NPU/Attention 指标。
- 不能把结果写成三 Attention 并行或 B/M 性能验收。

## 5. 证据

```text
docs/evidence/v3_functional_bar_20261102/m3_batch3_30rounds_20261103.json
docs/evidence/v3_functional_bar_20261102/m3_batch3_30rounds_20261103.log
```

板子已 recovery，无遗留 host 进程。
