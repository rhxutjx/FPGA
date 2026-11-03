# PC2 B bit batch=1：3 预热 + 30 轮结果（2026-11-03）

状态：**PASS_B_BATCH1_30ROUNDS**  
模式：B bit；B batch=1；每轮三条 prompt 顺序执行；不是 M；不是 B/M 同轮混合。

## 1. bit 判定

当前板上用 B 的 layer14 M golden：
- p0..31 匹配；
- frame 65 / pos32 开始不匹配。

这与 B 的 FP16 KV 与 M 的 tail/压缩策略差异一致，判定当前板为 B bit。  
PC2 仍无法读取 bitstream hash；B bit 身份来自行为与 B 下载记录，不是板上 hash 回读。

## 2. 口径

- 三条 prompt：Tim / Spot / Mia；
- 每轮三条 prompt **顺序**执行（B batch=1）；
- 每 prompt 最多 8 token，greedy，EOS=0；
- 每轮/每条全局 RESET；
- 3 轮预热，排除；
- 30 轮正式测量；
- 计时含 RESET、prefill、NPU、PCIe、FPGA Attention、host；
- 不含模型加载/context 创建。

## 3. 结果

| 项 | 值 |
|---|---:|
| 正式轮数 | 30 |
| 每轮 tokens | 24 |
| 总 tokens | 720 |
| 总墙钟 | 4193.822 s |
| aggregate | **0.17168 output tokens/s** |
| mean/轮 | 139.794 s |
| p50 | 139.921 s |
| p95 | 140.282 s |
| min | 138.332 s |
| max | 140.395 s |

- 30/30 成功，无失败、无 EOS 提前停止。
- B 输出固定：
  - Tim：`" look nice.\"\nTim went to the"`
  - Spot：`" pretend to be a superhero. But sometimes"`
  - Mia：`" box full of different things.\n\n"`
- 与 M 的输出在 pos32 后不同，符合 B FP16/M tail 策略差异。

## 4. B vs M batch3

| 方案 | mean/轮 | aggregate |
|---|---:|---:|
| B batch=1 | 139.794 s | 0.17168 |
| M batch=3 | 116.401 s | 0.20618 |

M batch3 相对 B batch1：

- 墙钟快约 **16.7%**
- 吞吐高约 **20.1%**

注意：M 的 Attention 仍单帧在途；收益来自 NPU batch=3，不是三 Attention 并行。

## 5. 边界

- B bit 身份是行为判定，不是板上 hash 回读。
- B 这个 30 轮是 B batch=1 **顺序**；不是 B batch=3。
- 没有 B 的独立 Attention golden；没有 B/M 同输入逐帧数值对拍。
- B/M 输出差异来自策略，不得当质量优劣结论。
- 计时含每轮 RESET；8-token 短生成；不是纯 NPU/Attention。

## 6. 证据

```text
docs/evidence/v3_functional_bar_20261102/b_batch1_30rounds_20261103.json
docs/evidence/v3_functional_bar_20261102/b_batch1_30rounds_20261103.log
```

板子已 recovery，无遗留 host 进程。
