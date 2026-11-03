# PC2 M 单 session × 3 prompt × 30 轮结果（2026-11-03）

状态：**PASS_M_3SINGLE_30ROUNDS**  
模式：**M single-session sequential；不是 batch3，不是 B/M 对比。**  
bit：functional BAR 版 `3BC476B360470EBB8126B6509372C20AD1518EC2E8BC1633F489A5CB0BF87A8D`（B 文件；板上 hash 未回读）。

## 1. 口径

- 3 个 prompt：Tim / Spot / Mia；
- 每个 prompt 单独 session，顺序跑 **30 轮**；
- 每轮 8-token greedy，`MAX_NEW_TOKENS` 停止；
- 每轮 `M3Attention.reset` 做全局 RESET，新建会话；
- 模型/NPU 常驻，加载排除；
- 单进程、一次 recovery，无跨轮 recovery；
- 计时包含该轮 tokenizer、NPU linear、PCIe、M FPGA Attention、host 调度；不含模型加载。
- **没有 batch3，也没有 B bit。**

## 2. 汇总

| prompt | 轮数 | tokens | mean wall | p50 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| Tim | 30 | 240 | 46.305 s | 46.898 | 47.274 | 40.574 | 47.406 |
| Spot | 30 | 240 | 47.233 s | 47.234 | 47.384 | 46.969 | 47.404 |
| Mia | 30 | 240 | 47.265 s | 47.263 | 47.366 | 47.117 | 47.535 |
| **合计** | **90** | **720** | — | — | — | — | — |

- 总墙钟：**4225.834 s（约 70.43 min）**
- aggregate：**720 / 4225.834 = 0.17038 output tokens/s**
- 90/90 成功，无失败、无 EOS 提前停止，全部 8 token、`MAX_NEW_TOKENS`。

## 3. 生成结果（每 prompt 30 轮一致）

```text
Tim:
  ids [1492, 9239, 1270, 198, 3681, 2637, 260, 15038]
  text " look nice.\"\nHe took the truck"

Spot:
  ids [722, 357, 288, 919, 17025, 4598, 30, 1249]
  text " use it to make funny sounds. But"

Mia:
  ids [3985, 282, 1114, 30, 476, 1780, 506, 338]
  text " box of food. \"What's that"
```

## 4. 边界

- 这是 **M 单 session 的重复生成性能/稳定性**，不是 M batch3 的 30 轮。
- 没有独立 full-model M golden；只记录 actual M 输出，不证明自由生成正确性。
- 不能用于 B/M 对比；B bit 没有本次 `0x212000/0x212800` 修正和同 harness 板测。
- 0.170 tok/s 是单 session、8-token 短生成，包含每轮全局 RESET；不是 attention-only/NPU-only 指标。
- 第一轮 Tim 40.57 s，后续约 47 s；可能包含首次轮次/缓存差异，未单独做预热排除；后续统计已按全部 30 轮计算。

## 5. 证据

```text
docs/evidence/v3_functional_bar_20261102/m3_3x30_20261103.json
docs/evidence/v3_functional_bar_20261102/m3_3x30_20261103.log
```

板子已执行 recovery；无遗留 host 进程。
