# 4 天初步计划：M 加速、PCIe 优化与更大模型可行性

日期：2026-10-28（D1–D4 可按实际日期平移）
状态：**初步计划，待老师/PC1/B 确认目标模型与可用制品**

## 0. 一句话结论

**4 天内可以完成：PCIe 瓶颈测量与优化、当前模型（或已有预置 bit 的更大模型）的 B/M 对比、M 速度/内存 trade-off 证据。**
**4 天内不能安全完成：从零换一个不同 shape 的新模型 + 新 FPGA bit + 新 NPU 制品 + 新评测。**

大模型不是“改几个代码文件”，关键取决于：

1. 是否有**已经综合好的 B/M bit**；
2. PC1 是否有对应的**NPU linear 制品、tokenizer、profile、HF/PPL 参考**；
3. 新模型是否仍是当前 bit 支持的 shape（30 层、H9/G3、D64、H576/FFN1536、vocab49152、T≤256）。

任何一项不满足，就必须在 **D1 中午**切到 fallback，否则 4 天会被 bit/NPU 集成吃掉。

## 1. 背景与现状（事实）

- 当前正式模型：SmolLM-135M；方案 C，RK3576 NPU + PH1A90 FPGA。
- 已完成的 30 条 B/U/M 板上数据（TinyStories BOS，2509 token）：

| 模式 | PPL | next-token acc | KV 模型值 | mean forward |
|---|---:|---:|---:|---:|
| B | 6.294 | 55.0% | 5.625 MiB | 1.643 s |
| U | 9.581 | 50.1% | 1.113 MiB | 2.329 s |
| M | 6.439 | 55.0% | 1.875 MiB | 2.069 s |

- M 相对 B：质量接近（PPL +2.3%），KV 约 3× 压缩；但**速度比 B 慢**（M 2.069s vs B 1.643s）。
- M 相对 U：质量明显更好（PPL -3.14，accuracy +4.86pp），但 KV 比 U 多。
- v50 live demo：prompt 1，35 BOS token + 8 new，42 位置、1260 FPGA Attention、67.5s；M fixed post-tail probe 1950 帧通过。
- 当前 M bit：30 层、H9/G3、D64、T≤256；M policy 固定 K3=14/18/26、V4=14/22/23、tail=32。
- 当前驱动：`poll_mode=0`（中断模式），`force_st_c2h_wb=0`；`poll_mode=1` 会丢 C2H completion，已在长 run 复现。
- 板卡 4GB LPDDR4X；FPGA DDR 256MiB；当前模型 KV 远小于 DDR；更大模型才可能让 KV/内存成为主要矛盾。
- 本机有 TD 2026.1 SP2；但 B 的 M TD 工程（`E:\KVmix\...`）不在本机；当前只有 `.bit` 和通用算子 RTL，不能从 `.bit` 反推/修改。

## 2. 目标（必须 / 尽量）

### 必须完成
1. **PCIe 分阶段计时**：H2C submit、H2C wait、C2H wait、C2H read、校验/证据写入；每层/每 token p50/p95；30 层串行开销。
2. **PCIe 优化**：至少减少 host 提交/同步/拷贝开销；保持 poll_mode=0；不改变 wire contract；不破坏 B/M 正确性。
3. **B/M 同条件对比**：同一模型、同一 profile、同一 seq 规则，B baseline vs M；质量 + KV + end-to-end/PCIe 时间。
4. **一个可演示结果**：v50 M live demo 或等价 B/M 小 demo；记录 bit、模型、profile、驱动参数。
5. **证据包**：报告、summary、计时、失败/恢复记录；可复现。

### 尽量完成
- 更大模型（若 D1 中午前确认 bit/NPU/profile 全齐）。
- U 作为补充，不作为主线。
- BUM compare / Pareto 图。
- PCIe 与 Attention 的拆分和收益归因。

### 不在 4 天内承诺
- 从零新建不同架构/不同 shape 的大模型 bit + TD/P&R + NPU 制品 + HF 评测。
- 7B 模型上板（4GB 权重常驻不成立；当前 FPGA shape/ERAM 也不支持）。
- 论文级 4.9×/5.3× 或完整 BUM 统计结论。

## 3. 关键决策：大模型走 A 还是 B

### 计划 A：大模型上板（仅在预置制品齐全时）
前提（D1 中午前全部确认）：
- 目标模型 config：层数、hidden、FFN、Q/KV heads、head_dim、vocab、context；
- **已有 B bit 和 M bit**（或 B 能在 D1 当天出 bit）；
- PC1 已有该模型的 NPU linear 制品、tokenizer、embedding/LM head、profile、HF/PPL 参考；
- 新模型仍在 4GB/NPU/FPGA 可承受范围（建议 ≤1B W8，且 shape 与 bit 匹配）。

若满足：
- D1 PM 集成模型；B/M 固定 probe；
- D2 跑 B/M 小样本 + PCIe 计时；
- D3 跑完整对比/演示；
- D4 证据/报告。

### 计划 B：大模型不上板（默认 fallback）
保留 SmolLM-135M 板级 M/B；大模型只在 PC/GPU 侧做质量/内存动机对比，不声称板级结果。

理由：
- 新架构的 bit/NPU 集成不是 4 天能稳定完成的；
- 4 天更值得把**M 的 speed/memory trade-off**和 **PCIe 实际开销**做扎实；
- 老师要的“更大模型让 M 的内存收益更明显”可以用 PC 侧大模型分析 + 板级当前模型 M/B 组合呈现，但必须明确边界。

### 计划 C：从零换模型
**不建议，4 天内不立项。** 只有老师明确接受“可能只得到部分结果/无完整 bit”才做。

## 4. 四天排期

> 原则：D1 中午是 Go/No-Go；D4 中午后不再加新功能，只做证据和报告。

| 时间 | 工作 | 负责 | 交付/门 |
|---|---|---|---|
| D1 AM | 冻结目标模型；盘点 bit/NPU/tokenizer/profile/HF；确认板卡 M bit、poll_mode=0、独占；PCIe baseline 计时方案 | 全组/PC1/B/PC2 | **D1 12:00 Go/No-Go：A 或 B** |
| D1 PM | A：集成大模型 + B/M probe；B：PC 侧大模型质量/内存 baseline；PC2 做 PCIe submit/wait/read 拆分 | PC1/B/PC2 | 目标模型集成结论；PCIe baseline 表 |
| D2 AM | PCIe 优化第一批：持久 fd/预分配 buffer、减少 per-request 文件写入、预挂 C2H、poll_mode=0、减少 host 拷贝/同步 | PC2 | 优化前后同 workload 对比 |
| D2 PM | A：B/M 小样本跑通 + 正确性；B：当前模型 M/B + PCIe 优化；必要时保留回滚 | PC2/PC1 | 正确性 Gate：M probe/B probe 通过 |
| D3 AM | 跑 B/M（A：大模型；B：当前模型）质量+速度；记录 KV、PPL/accuracy、PCIe p50/p95、end-to-end | PC1/PC2 | B/M 结果表 |
| D3 PM | v50/等价 demo；失败/恢复记录；准备 Pareto/图表；决定是否加 U | PC2/PC1 | demo + 初版结果 |
| D4 AM | 复跑关键结果；整理证据包、报告、演示；老师可审 | 全组 | 可交付报告 |
| D4 PM | buffer；只修证据/文档，不加新功能 | 全组 | 最终提交 |

## 5. 工作流与负责人

| 角色 | 负责 | 4 天内的具体产出 |
|---|---|---|
| PC1 | 模型/NPU/reference/profile/HF/PPL | 目标模型 config、tokenizer、NPU linear 制品、profile、HF/PPL、B baseline |
| PC2 | PCIe transport、板级 run、计时、证据 | PCIe baseline/优化、M/B 跑板、v50、失败/恢复记录 |
| B | M/B bit、TD/P&R、RTL | 目标模型 bit（若 A）；M bit 源码/构建；如只能当前模型，确认 bit 与回滚 |
| 老师 | 目标/范围/验收 | D1 中午确认 A/B；D4 验收 |

## 6. PCIe 优化具体项（PC2）

先测再改，目标是把“每层 30 次串行交互”的真实成本拆开：

1. **分阶段计时**
   - H2C submit / H2C wait / C2H wait / C2H read / CRC/seq 校验 / 证据落盘。
   - 每层、每 token、30 层累计；p50/p95/max；区分 transfer 与 sync。
2. **减少 host 开销**
   - 持久 fd、预分配/复用 pinned buffer；
   - 避免每请求写 logits/证据（改为批量/结束写）；
   - 复用 codec buffer；减少 Python 对象/拷贝；
   - `poll_mode=0` 保持；不做未验证的 MSI/ASPM/实时调度改动。
3. **减少同步/等待**
   - 预挂 C2H、减少不必要的 status/日志轮询；
   - 在不破坏 v2 单请求在途/seq 语义的前提下，测试可安全重叠的 submit/read；
   - 任何 pipeline 必须证明 seq/CRC/KV 顺序不变。
4. **协议/布局**
   - 32B header + 1920/1152 payload 已固定；不擅自加 padding/改 magic；
   - 若 PCIe 不是主瓶颈，不投入大改；
   - 记录 Gen2 x1 理论/实际、DMA 对齐、短读/超时。
5. **验收**
   - 同 workload 优化前后：每层 RTT、30 层链、token latency、错误数；
   - M/B 同条件；正确性 probe/OP_TEST 通过；不引入 C2H 新故障。

## 7. 大模型可行性清单（D1 中午必须回答）

- [ ] 目标模型名称/参数量/config？
- [ ] 是否与当前 bit shape 一致？若否，谁出 bit、TD 工程在哪、D1 能否出？
- [ ] B bit 和 M bit 是否已有？hash？
- [ ] PC1 NPU 制品是否已有（211 linear/层结构、LM head、embedding）？
- [ ] tokenizer/profile/HF/PPL 是否已有？
- [ ] 4GB 内存/FPGA DDR/ERAM 是否在安全范围？
- [ ] 评测样本/时间是否够？

**任一关键项为“否”→ 走 Plan B，不把 4 天押在新模型集成上。**

## 8. 风险与回滚

| 风险 | 影响 | 应对 |
|---|---|---|
| 新模型 shape 不匹配 | 需要新 bit/TD/P&R，4 天不够 | D1 中午前确认；否则 Plan B |
| 新 bit 掉电/恢复丢失 | 板上回到 U/默认 bit | B 烧录后立即验证 M probe；保留 bit 文件/hash |
| C2H completion 丢失 | 长 run 随机失败 | 保持 poll_mode=0；失败即停；恢复后新 seq 重跑 |
| PCIe 优化引入协议错误 | 数据/KV 错 | 只做可控 host 优化；每步 probe/OP_TEST；保留回滚 |
| 大模型质量/PPL 不达预期 | 老师目标落差 | 先 PC 侧 baseline；板上只报实测，不夸大 |
| 4 天时间不够 | 结果不完整 | D4 中午冻结；交付“已完成/未完成/边界” |

## 9. 最终交付物

- 1 份 4 天报告（目标模型/最终模型、B/M 配置、bit/hash、驱动参数）。
- B/M 结果表：PPL、next-token accuracy、KV bytes、end-to-end/PCIe 时间。
- PCIe 分阶段计时表 + 优化前后对比。
- v50/等价 demo 证据（summary/report tar）。
- 失败/恢复记录、原始 logits 路径、复现命令。
- 明确边界：哪些是板级实测，哪些是模型值/PC 侧估计；大模型是否真的上板。

## 10. 今天立即要做的事

1. 老师/PC1 给出目标大模型名称与 config；B 确认是否已有 B/M bit 和 TD 工程。
2. PC2 立刻做当前 M/B 的 PCIe 分阶段 baseline（不改功能）。
3. D1 12:00 前做 A/B 决策；B 方案默认保留 SmolLM-135M。
4. 板卡保持：M bit、`poll_mode=0`、独占、无其他测试进程；记录 last seq。

---

**给老师的沟通要点：**
4 天内，PCIe 优化 + 当前/预置大模型 B/M 对比是可行的；从零换一个不同 shape 的大模型并重做 bit/NPU/评测，风险远大于收益。若老师坚持新模型，需要你们在 D1 中午前提供可用的 bit、NPU 制品和 profile，否则建议按 Plan B 交付，并把大模型质量/内存分析放在 PC/GPU 侧。
