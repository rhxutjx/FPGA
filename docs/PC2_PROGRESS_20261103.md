# PC2 当前进度（2026-11-03）

状态：**B/M v3 functional 实板已跑通；性能对比完成；完整质量指标仍未完成。**  
仓库基线仍是 2026-09-30 的 PLAN；本文记录之后新增、已实测的事实，不修改冻结的模型/架构选择。

## 1. 结论摘要

- `v3` 多 session / functional BAR 映射已在 PH1A90 + RK3576 实板跑通。
- **M functional bit** 通过：
  - layer14 70 帧 golden：70/70
  - PC1 v48 30 层 ×84 位置：2520/2520
  - B 的 Spot/Mia B golden：2100/2100
  - RESET/TEST、多 session、FAULT、SOFT_RESET
- **B bit** 通过：
  - B 自己的 Spot/Mia golden：2100/2100
  - B batch=1 3 预热 +30 轮
- **M NPU batch=3** 3 预热 +30 轮完成，性能优于 B batch=1。
- 目前没有独立 full-model 质量参考/PPL 对拍；不能下“谁质量更好”的结论。

## 2. 当前实板与 bit

- 板卡：RK3576 EVB，SSH `kvdev@192.168.137.101`，串口 COM11 1500000 root。
- 当前板上：**B bit**（用 M golden 在 pos32 失配判定；B golden 2100/2100 通过）。
- B bit 目标 hash（B golden 声明）：`9DE62201DBF05ADB0DC094F4447150E4422158EB8CFA8E4B1F251554DBAD2A02`。
- M functional bit：`3BC476B360470EBB8126B6509372C20AD1518EC2E8BC1633F489A5CB0BF87A8D`。
- PC2 无法从板上回读 bitstream hash；身份依赖烧录记录 + 行为/golden。
- H2C 跨进程不可复用：一进程一 recovery；串口 root `/usr/local/sbin/pcie1-recover.sh`。

## 3. v3 BAR 映射（已实测）

诊断 bit 的 AXI trace：

```text
BAR0 0x5C    -> AXI 0x2120005C
BAR0 0x8005C -> AXI 0x2128005C
BAR0 0xAC    -> AXI 0x212000AC
BAR0 0x800AC -> AXI 0x212800AC
```

functional bit 解码两个窗口：

```text
STATUS  0x212000A4 / 0x212800A4
CONTROL 0x212000A8 / 0x212800A8
VERSION 0x212000AC / 0x212800AC
```

实板读到 `VERSION=0x504C4233`、`STATUS=0x00FF0010`。  
详见：`pcie_contract/PC2_BAR_DIAG_RESULT_20261102.md`、`pcie_contract/PC2_FUNCTIONAL_M_BOARD_TEST_20261102.md`。

## 4. 性能结果（同三条 prompt、8-token greedy）

| 方案 | 轮数 | mean/轮 | aggregate |
|---|---:|---:|---:|
| B batch=1 | 3 预热 +30 | 139.794 s | **0.17168 tok/s** |
| M single session ×3（顺序） | 30 each | — | 0.17038 tok/s |
| M host interleaved 3 session | 5 | 162.390 s | 0.14779 tok/s |
| **M NPU batch=3** | 3 预热 +30 | **116.401 s** | **0.20618 tok/s** |

- M batch=3 相对 B batch=1：吞吐高约 **20.1%**，墙钟快约 **16.7%**。
- Attention 仍是**单帧在途、逐请求处理**；batch=3 只批量化 NPU linear，不是三 Attention 并行。
- 交错调度本身比顺序慢约 9–15%，不建议作为性能方案。

## 5. 质量/参考现状

- PC1 v50 CPU-attention reference 已生成 3 prompts 的 8-token 输出和逐 step logits（仅 generated steps）。
- token match vs reference：
  - B：Tim 4/8、Spot 8/8、Mia 1/8，总 13/24
  - M：Tim 5/8、Spot 0/8、Mia 3/8，总 8/24
- 当前 logits 是 reference 自己轨迹的 logits；B/M 分叉后不能直接用于有效 PPL。
- 要得到有效 PPL/next-token，需要对 B/M 实际 token 序列做 reference teacher-forced forward。
- M logits 尚未采集；需要 B 烧回 M functional bit。
- 没有严格 HF full-model reference；当前参考是 PC1 v50 NPU + CPU attention，必须标清。

## 6. 证据位置

```text
pcie_contract/
  MULTI_SESSION_INTERFACE.md
  contract_v3_session.json
  golden_vectors_v3.json
  multisession_v3.py
  PLAN_B_STATUS_V3.md / plan_b_status_v3.json
  PC2_FUNCTIONAL_M_BOARD_TEST_20261102.md
  PC2_B_BATCH1_30ROUNDS_20261103.md
  PC2_M_BATCH3_30ROUNDS_20261103.md
  PC2_BM_GENERATED_OUTPUT_COMPARISON_20261103.md
  PC2_PC1_CPU_REF_3PROMPTS_20261103.md
  PC2_B_GOLDEN_2100_20261103.md

docs/evidence/
  v3_functional_bar_20261102/
    m3_batch3_30rounds_20261103.json
    b_batch1_30rounds_20261103.json
    pc1_ref_logits_3prompts/
    b_logits_3prompts/
  v3_bits_20261031/
  npu_batch_20261030/
```

## 7. 下一步

1. 对 B/M 实际 token 序列做 reference teacher-forced logits 采集，算有效 NLL/PPL/next-token。
2. B 烧回 M functional bit + recovery，采 M logits。
3. 补严格 HF full-model reference（若团队要求）。
4. B/M 30 轮正式对比已经完成，不必重复性能测试；若要更多重复性可另跑。
5. B/M bit 的 timing/CDC 仍未签核，不能把当前结果当最终可靠性验收。
