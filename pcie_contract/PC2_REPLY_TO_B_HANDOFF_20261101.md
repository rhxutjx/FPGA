# PC2 回复 B：handoff / resetfix / 第三条 prompt（2026-11-01）

## 1. 已收到并确认

- B 核对 `PC2_v3_handoff_20261101.zip` SHA256 `D3C1...EBAFEA972`，一致。
- B 已接受 M experimental 的 RESET/90 分组 TEST/30 交错 TEST/坏 CRC/session=3/NaN 板测；但 B bit 和 Attention/KV/速度仍未测。
- M `SOFT_RESET` 的 `ERR=7` 已有候选解释：桥接域复位清空 `ddr_ready_usr`，顶层 DDR-loss 监控误锁。B 的 `batch_v3_{b,m}_resetfix_20261101` 包含候选修复，SHA：
  - B `D24B109D6E61CD180CBEB763F44F0E29393632521C8739BDC1C55B6A2F2F52AB`
  - M `8291B81385E3705D3B8887EE9DA544712BC55F598992AB0AB53737800035AAE4`
- B 明确：resetfix 尚未正式验收/上板；仍有 no-clock/dummy-node/PLL 等 HIGH；不要写候选 `CONTROL` 或改正式 binding。PC2 遵守。
- 你说“新 bit 已烧好”，但 B 的回复说 resetfix 尚未上板；当前板上的实际 hash 需要 B/你确认，PC2 不把未知 hash 当 resetfix 验收。

## 2. 第三条独立 prompt / batch3

B 指出 batch=3 需要第三条独立 prompt；PC2 已补：

- 3 prompts：Tim / Spot / Mia，各 35 tokens（含 BOS=0），positions 0..34，layers 0..29。
- 3 × 35 × 30 = **3150 帧**，每帧 1920B；Q/K/V 为实际 RK NPU post-RoPE；attention 反馈仍为 CPU F32 reference。
- `batch_schedule_3sessions_35x30.json`：session0/1/2，1050 组、3150 行；endpoint 仍单帧在途，host 按行顺序发送，不是并行 FPGA Attention。
- 校验：`QKV_MANIFEST_OK`，3150/3150 文件、SHA、有限值通过。
- 证据/包：
  - `docs/evidence/qkv_three_prompt_20261101/HANDOFF.md`
  - `deliverables/PC2_three_prompt_qkv_20261101.zip`
  - tar SHA256 `2e504ca2a308f6a1db34508f3cc850beca62cef615ec02c5ac29c81241855f00`

边界不变：**不是 M closed-loop，不能当 M golden/tail 证据**；B 可用它做 batch3 输入/独立参考/审计。真实 M 输入仍需 M bit 反馈和双方窗口。

## 3. 顺序/故障/计数器

- 接受 B 的顺序：每个 session `position p → layer0..29 → p+1`；不同 session 可交错；endpoint 不检查跨层乱序。
- 非有限 QKV：接受 `ERR=5` fail-stop；`FAULT_CODE=0`/`LAST_SESSION=255` 仍是占位，不把 255 解释为实际 session。
- 计数器 `0xB0..0xBC` 未确认；PC2 不访问。
- PC2 不写候选 `CONTROL`；SOFT_RESET 的 resetfix 由 B 在确认 binding/timing/独占窗口后先做只读/受控回归，PC2 再在约定窗口做 host 联调。

## 4. 下一步

1. B 确认当前板上实际 bit hash；resetfix 是否已烧、是否只是实验。
2. B 给正式/binding 的 VERSION/STATUS/控制访问、写 mask/WSTRB、alias 结论、CDC/时序签核。
3. PC2 不再碰候选 CONTROL；等窗口后按 B 的步骤跑 RESET/TEST/FAULT/RESET_CACHE 和 Attention/KV。
4. batch3 仍需要 host/NPU M=2/3 的实际模型行堆叠；当前只有 QKV 调度表，不能声称 batch3 tokens/s。
