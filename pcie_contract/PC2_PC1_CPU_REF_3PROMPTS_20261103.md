# PC1 v50 CPU-attention 全模型参考（2026-11-03）

状态：**参考生成完成；B/M token match 已算；PPL 未算。**  
参考路径：PC1 v50 NPU linear + CPU F32 attention，不接 B/M bit；不是 HF reference，但独立于 B/M Attention。

## 1. 参考生成

- 3 prompts：Tim / Spot / Mia；
- 35 token prompt，8-token greedy；
- 参考总墙钟：155.739 s；
- 结果每轮固定。

| prompt | reference token IDs |
|---|---|
| Tim | `[1492, 9239, 1270, 198, 3681, 3413, 650, 2910]` |
| Spot | `[24327, 288, 325, 253, 15613, 30, 1249, 2406]` |
| Mia | `[3985, 282, 8809, 30, 21230, 3683, 982, 699]` |

## 2. B/M token match

| prompt | B match /8 | M match /8 |
|---|---:|---:|
| Tim | 4 | 5 |
| Spot | **8** | 0 |
| Mia | 1 | 3 |
| **合计** | **13/24** | **8/24** |

三条输出：

```text
Tim:
  ref [1492, 9239, 1270, 198, 3681, 3413, 650, 2910]
  B   [1492, 9239, 1270, 198, 17170, 3514, 288, 260]
  M   [1492, 9239, 1270, 198, 3681, 2637, 260, 15038]

Spot:
  ref [24327, 288, 325, 253, 15613, 30, 1249, 2406]
  B   [24327, 288, 325, 253, 15613, 30, 1249, 2406]   # 8/8
  M   [722, 357, 288, 919, 17025, 4598, 30, 1249]

Mia:
  ref [3985, 282, 8809, 30, 21230, 3683, 982, 699]
  B   [3985, 2073, 282, 896, 1495, 30, 198, 198]
  M   [3985, 282, 1114, 30, 476, 1780, 506, 338]
```

## 3. 能下的结论

- 参考路径可用；
- B 在 Spot 上 8/8 与参考一致；
- B/M 与参考在 Tim/Mia 都有分歧；
- 仅凭 token match 不能判定整体质量；8-token 短生成、无 PPL；
- 不能把“B Spot 8/8”外推为 B 整体更好，也不能把 M 的 8/24 当质量结论。

## 4. 仍未做

- 每步 logits / PPL / next-token accuracy；
- 更多 prompt、固定测试集、统计置信度；
- 严格 HF reference（当前是 PC1 v50 NPU+CPU attention）；
- B/M 与参考的逐 step NLL。

## 5. 证据

```text
docs/evidence/v3_functional_bar_20261102/pc1_cpu_ref_3prompts_20261103.json
```

本次只运行 CPU attention 参考，没有访问 B/M FPGA，也没有改 bit。
