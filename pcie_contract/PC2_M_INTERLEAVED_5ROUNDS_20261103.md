# PC2 M 三 session 交错 5 轮结果（2026-11-03）

状态：**PASS_M_INTERLEAVED_5ROUNDS**  
模式：host 三 session 交错/并发推进；M endpoint 单帧在途、Attention 逐请求；不是三路并行，也不是 batch3。

## 1. 每轮墙钟

| round | wall |
|---:|---:|
| 1 | 155.338 s |
| 2 | 162.273 s |
| 3 | 163.915 s |
| 4 | 162.821 s |
| 5 | 167.602 s |

- mean：**162.390 s**
- p50：**162.821 s**
- min：155.338 s
- max：167.602 s
- 每轮 24 output tokens；aggregate：**24 / 162.390 = 0.14779 tokens/s**
- 5/5 成功，无失败、无 EOS 提前停止；每 session 8 token、1260 Attention calls。

## 2. 对比顺序单 session

之前 3 个单 session 各 30 轮：

```text
顺序三条一轮约 140.803 s
aggregate 0.17045 tokens/s
```

本次交错：

```text
均值 162.390 s
aggregate 0.14779 tokens/s
```

即交错比顺序：

- 墙钟慢约 **15.3%**；
- 吞吐低约 **13.3%**；
- 第 1 轮 155.3 s 后没有回到顺序水平，后 4 轮在 162–168 s，趋势还略有上升。

## 3. 解释

- 三个 session 的 host 时间重叠，但：
  - M Attention 单帧在途；
  - transport 有全局锁；
  - NPU engine 共享并加锁；
  - 线程切换和串行化抵消了重叠收益。
- 所以不是“第一轮慢”，而是 **5/5 都慢**。
- 该结果符合 endpoint 单帧在途的限制；不能称为三 Attention 并行或 batch3 提升。
- 本测试没有 B bit，不能做 B/M 对比；没有独立 full-model M golden。

## 4. 证据

```text
docs/evidence/v3_functional_bar_20261102/m3_interleaved_5rounds_20261103.json
docs/evidence/v3_functional_bar_20261102/m3_interleaved_5rounds_20261103.log
```

板子已 recovery，无遗留 host 进程。
