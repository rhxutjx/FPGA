# B/M 完整生成输出对比（2026-11-03）

状态：**输出对比完成；不是质量结论。**  
数据来源：B batch1 30 轮、M batch3 30 轮；两边都使用三条相同 prompt、8-token greedy、全局 RESET，输出每轮一致。

## 1. 生成结果

| prompt | B batch1 | M batch3 | 共同前缀 |
|---|---|---|---:|
| Tim | `[1492, 9239, 1270, 198, 17170, 3514, 288, 260]` | `[1492, 9239, 1270, 198, 3681, 2637, 260, 15038]` | 4 |
| Spot | `[24327, 288, 325, 253, 15613, 30, 1249, 2406]` | `[722, 357, 288, 919, 17025, 4598, 30, 1249]` | 0 |
| Mia | `[3985, 2073, 282, 896, 1495, 30, 198, 198]` | `[3985, 282, 1114, 30, 476, 1780, 506, 338]` | 1 |

文本：

```text
B Tim:  " look nice.\"\nTim went to the"
M Tim:  " look nice.\"\nHe took the truck"

B Spot: " pretend to be a superhero. But sometimes"
M Spot: " use it to make funny sounds. But"

B Mia:  " box full of different things.\n\n"
M Mia:  " box of food. \"What's that"
```

## 2. 能下的结论

- B/M 生成路径都实际跑通；
- 两边在相同输入下产生了不同的后续 token；
- 差异与 B/M Attention/KV 策略不同一致；
- 不能仅凭输出差异判断哪个质量更好；
- 没有独立 full-model reference，所以没有 PPL、next-token accuracy 或“谁更正确”的结论。

## 3. 为什么不能算质量

要算质量需要：

- 独立的完整模型 reference（HF/PC1 full-model）；
- 固定测试集和评分口径；
- 相同 prompt、tokenizer、采样、停止规则；
- 逐 token/logit 或 PPL 对照。

现在的 B/M 各自 golden 都是 **Attention 固定输入诊断**，不是完整模型质量 reference。

## 4. 性能对比（已有）

| 方案 | mean/轮 | aggregate |
|---|---:|---:|
| B batch=1 | 139.794 s | 0.17168 tok/s |
| M batch=3 | 116.401 s | 0.20618 tok/s |

M batch3 相对 B batch1：吞吐高约 **20.1%**，墙钟快约 **16.7%**；Attention 仍单帧在途。

## 5. 证据

```text
docs/evidence/v3_functional_bar_20261102/b_batch1_30rounds_20261103.json
docs/evidence/v3_functional_bar_20261102/m3_batch3_30rounds_20261103.json
```

板子已 recovery，无遗留 host 进程。
