# PC2 M 三 session 交错调度结果（2026-11-03）

状态：**PASS_M_INTERLEAVED_3SESSION（单轮）**  
模式：**host 三 session 并发交错；M endpoint 单帧在途、Attention 逐请求；不是三路 Attention 并行，也不是 batch3。**

## 1. 实现

- 三个 prompt：
  - session0 Tim
  - session1 Spot
  - session2 Mia
- 一次全局 RESET；
- 三个 host 线程同时启动，各自维护 token/position/hidden；
- 211 个 NPU linear context 共享，engine 调用加锁；
- v3 transport 单帧在途，Attention 请求串行；
- 三个 session 在时间上重叠推进，Attention 仍逐帧处理。

## 2. 单轮结果

| session | prompt | wall | output tokens | attention calls |
|---|---|---:|---:|---:|
| 0 | Tim | 153.914 s | 8 | 1260 |
| 1 | Spot | 153.789 s | 8 | 1260 |
| 2 | Mia | 154.025 s | 8 | 1260 |
| **合计** | — | **154.027 s** | **24** | **3780** |

- aggregate：**24 / 154.027 = 0.15582 output tokens/s**
- 三条输出与单 session 结果一致：
  - Tim：`" look nice.\"\nHe took the truck"`
  - Spot：`" use it to make funny sounds. But"`
  - Mia：`" box of food. \"What's that"`
- 无失败、无 EOS 提前停止，全部 8 token/MAX_NEW_TOKENS。

## 3. 与之前顺序单 session 对比

之前 3 个单 session 各 30 轮：

- aggregate：**0.17038 tokens/s**
- 三条各一次的顺序时间约：
  ```text
  46.305 + 47.233 + 47.265 = 140.803 s
  ```
- 对应 aggregate：24 / 140.803 = 0.17045 tokens/s

本次交错：

```text
154.027 s，0.15582 tokens/s
```

即：

- 交错比顺序约慢 **9.4%**（wall） / 吞吐约低 **8.6%**；
- 三 session 时间重叠，但没有带来吞吐提升；
- 符合单帧在途、共享 NPU/transport 锁、逐请求 Attention 的预期。

## 4. 边界

- 这是 **1 轮**交错，不是 30 轮交错；
- 没有 B bit，不能做 B/M 对比；
- 没有独立 full-model M golden；
- 不能称为 3 Attention 并行；
- 不能把 0.1558 与 batch3 加速混为一谈；
- 共享 engine/transport 锁、线程调度和缓存都可能影响结果。

## 5. 结论

在当前 M functional bit（单帧在途、逐请求 Attention）下：

```text
三 session host 交错：能跑通
但相比三条顺序单 session：没有吞吐提升，反而约慢 8–9%
```

这符合“endpoint 单帧在途”的限制：重叠的是 host/session 调度，不是 Attention 计算。

## 6. 证据

```text
docs/evidence/v3_functional_bar_20261102/m3_interleaved_3sessions_20261103.json
docs/evidence/v3_functional_bar_20261102/m3_interleaved_3sessions_20261103.log
```

板子已 recovery；无遗留 host 进程。
