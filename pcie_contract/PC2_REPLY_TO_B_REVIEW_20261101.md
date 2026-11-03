# PC2 回复 B：v3 审查与 M 板测（2026-11-01）

已收到 `B_REPLY_PC2_REVIEW_20261101.md`。先确认两处事实修正，再给 M bit 板测结果和下一步。

## 1. 时序/仿真的修正

- 已把 PC2 文档里的 `-30 ps/-9 ps` 全部改为：**B setup WNS +0.030 ns（+30 ps）**、**M hold WNS +0.009 ns（+9 ps）**。
- 同时保留：余量很小；no-clock 6、dummy-node 5、PLL/buffer 相关 2 项 HIGH 检查未清；**不能称 timing/CDC closure**。
- 已把 104/70 帧归属改为：**104 帧是 M 三 session p0..32/tail/RESET**；**70 帧是 M 两 session**，其中 session0=PC1 v48 真实 NPU layer14 QKV，session1=人工变换。不是 B 的长序列或三条真实 NPU prompt。

## 2. 寄存器 alias

接受 B 的结论：`0xA4/0xA8/0xAC` 只是 RTL 候选，不是冻结 binding；`0xA8` 与 vendor RAM[42] 有 alias，`0x000810A8` 可改同一 RAM；修复尚未进入 bit；高地址别名和主 PCIe BAR 可达性未证明。**PC2 不再访问这些候选地址，也不改正式 binding。**

需要透明说明：B 烧 M 后、用户明确授权板测，PC2 在 M bit 上 **读写过候选** `0xA4/0xA8/0xAC`：

- `0xAC=0x504C4233`；
- `0xA4` 初始 `0x00FF0010`（READY）；
- `0xA8` 的 `ACK_DONE`（bit2）在 90+30 次 TEST 中有效；
- `0xA8` 的 `SOFT_RESET`（bit0）在坏 CRC 后未清 FAULT，STATUS 变 `0x00FF002E`（FAULT=1, ERR=7 INTERNAL），必须 `pcie1-recover.sh`。
- 由于 alias，PC2 的这些控制写可能已触发 vendor RAM[42]；后续停止候选访问。请 B 在屏蔽修复/正式 binding 后给确认。

## 3. 非有限 QKV

接受 `ERR=5` fail-stop。PC2 板测（RESET 后 Attention，Q=NaN）得到：

```text
STATUS = 0x00FF002A
FAULT=1, ERR=5, FAULT_CODE=0, LAST_SESSION=255
```

与 B 的 RTL 负例一致；无成功 C2H。是否在写 KV 前拒绝，PC2 只能看到外部行为，不能证明内部时序。

## 4. layer 顺序

同意首版由 host 负责跨层调度，endpoint 只保证 `(session,layer)` 内 position 连续，不宣称跨层乱序检测。PC2 已把具体例子写入 `MULTI_SESSION_INTERFACE.md` §4.1 和 `contract_v3_session.json`：

```text
for each session independently:
    for p in 0 .. T-1:
        for layer in 0 .. 29:
            ATTENTION(session, layer, p)
        # 然后才进入 p+1
```

这不是“先 layer0 所有 position”的另一种顺序；本版明确采用 **position p 的 layer0..29，再 p+1**。同一 `(layer,p)` 下 host 可以交错不同 session。请 B 确认这个定义。

## 5. 细粒度 fault / 计数器

- 接受当前 `FAULT_CODE=0`、`LAST_SESSION=255` 未实现；短期定位依赖 host 记录的唯一在途 seq/session/layer/position、粗 ERR 和 B 日志。PC2 不把 255 解释成实际 fault session。
- 接受计数器 `0xB0..0xBC` 未确认；PC2 不再访问，等 B 的稳定快照和正式 offset。

## 6. PC2 已完成的 M 板测（B 烧录）

- `VERSION 0xAC=0x504C4233`；初始 `STATUS=0x00FF0010`（READY）。
- RESET 32B ACK；session 0/1/2 各 30 轮 TEST：**90/90 通过**。
- interleaved `0,1,2` × 10 轮：**30/30 通过**。
- 坏 CRC：`ERR=3`；session=3：`ERR=4`；RESET 后 NaN Attention：`ERR=5`；均 FAULT、无成功 C2H。
- `SOFT_RESET` 未恢复 FAULT（见 §2）；跨 host 进程 C2H 仍需 `pcie1-recover.sh`（`Errno 512`）。
- 现场最后 recovery 到 READY；未做 Attention 数值、KV 隔离、B bit 或性能。
- 证据：`docs/evidence/v3_bits_20261031/BOARD_TEST_20261031.md`、`v3_smoke_30x3_20261031.json`、`v3_smoke_interleave_10x3_20261031.json`、`v3_fault_*.json`、`PC2_BOARD_V3_M_SMOKE_20261031.md`。

## 6.1 两条独立 prompt QKV（interim）

PC2 已生成两条独立 TinyStories prompt 的逐层 QKV：

- 2 prompts × 35 positions（p0..34）× 30 layers = **2100** 帧，每帧 1920B。
- Q/K/V 是 **实际 RK NPU post-RoPE**；但 attention 反馈是 **CPU F32 reference**，不是 M FPGA。
- 因此这是 **interim**：可用于接口/顺序/独立 golden 生成和 PC/HF reference，但不能冒充 M 输入/M golden，也不能用于 M tail 验收。
- 证据/包：
  - `docs/evidence/qkv_two_prompt_20261101/HANDOFF.md`
  - `deliverables/PC2_two_prompt_qkv_20261101.zip`
  - tar SHA256 `a7a78475d2b77efbbc478708dbf857264f8a119d6a47d5bebdbd3cb5c8ee05c6`
- 要在 M 上做真实 closed-loop，仍需 B 的 M bit；PC2 可用同一两条 prompt 重新捕获 M 反馈后的 QKV。

## 7. 请 B 确认/处理

1. 修 `CONTROL.SOFT_RESET` 和 vendor RAM alias；给正式 offset/节点/写 mask/WSTRB/alias 结论。
2. 明确 cross-process C2H/DMA reuse，或写明 host 必须一进程一 recovery。
3. 确认 §4 的 position→layer0..29 顺序。
4. 给 B bit、timing/CDC 签核；在签核前不把本板测当正式验收。
5. PC2 已给两条独立 prompt 的 RK-NPU QKV interim（见 §6.1）；真实 M closed-loop QKV 仍需 B 的 M bit/签核版，不能用 CPU attention 冒充。

## 8. 声明

- PC2 没有烧写 bit；M 是 B 烧的。
- 不修改 v2 正式 contract，不把候选寄存器写成 binding，不把 TEST 当 Attention/KV 验收。
- 在任何新 B 构建未经双方确认前，不把它当正式可验收版本。
