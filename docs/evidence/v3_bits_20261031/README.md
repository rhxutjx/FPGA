# B v3 experimental bitfiles（2026-10-31 接收）

状态：**已接收并做 SHA256 校验；未烧录、未上板、未作为可用 bit。**

来源：B 微信 `2026-10`；同时收到 `B_TO_PC2_V3_PROGRESS_20261031.md`。

| 文件 | 字节 | SHA256 | B 声明 |
|---|---:|---|---|
| `v3_b_experimental.bit` | 4,850,323 | `c62146718eee00d26872f431534479a35827b274a8d8066ae9bdc2503a5b06f2` | B：`C621...06F2`，**一致** |
| `v3_m_experimental.bit` | 4,850,323 | `25654eacc03949f131330ed3eda0ea370f1ade9095a199a9a7bd1d1dc3379fe4` | M：`2565...79FE4`，**一致** |
| `B_TO_PC2_V3_PROGRESS_20261031.md` | 2,985 | `866a726420c777b5de579cd200e5f80c13950c9d3b443d05dd800b18cf57c698` | B 进展原文 |

## B 报告的关键限制（原文事实）

- 完整综合/P&R 完成；B 报告 **B setup WNS +0.030 ns（+30 ps）、M hold WNS +0.009 ns（+9 ps）**，不是负值，但余量很小；两份报告仍有 no-clock 6、dummy-node 5、PLL/buffer 相关 2 项 HIGH 检查，不能称全面 timing/CDC closure。
- **B 当时未烧录/未上板**；仿真 104 帧是 **M 三 session p0..32/tail/RESET**，70 帧是 **M 两 session**（session0=PC1 v48 真实 NPU layer14 QKV，session1=人工变换）；不是 B 做过 104 帧长序列，也不是三条真实 NPU prompt。
- 控制寄存器仅是**本机工程候选**：逻辑 `0xA4` STATUS、`0xA8` CONTROL、`0xAC` VERSION，VERSION 候选 `0x504C4233`；现有顶层译码只检查低 16 位。B 已确认 `0xA8` 与 vendor RAM[42] alias，`0x000810A8` 可修改同一 RAM；修复尚未进入 bit。未确认物理 BAR、节点或 host 访问。
- B 当前 `FAULT_CODE=0`、`LAST_SESSION=255`；DONE 用 ACK_DONE 清除；带内 RESET ACK 不置普通 DONE；RESET_BUSY 与 READY 互斥。
- 非有限 QKV 当前按 protocol 拒绝，策略待双方确认。
- 当前只检查 `(session,layer)` 内的 position 顺序，**未证明跨层乱序检查**。

## 结论

文件真实性和 B 声明的 hash 一致；但 timing 未闭合、寄存器未绑定、真实 NPU 输入/golden 未到位，因此 PC2 **不应当把这个 bit 当可验证多 session bit 上板**，也不应按 `0xA4/0xA8/0xAC` 直接改正 binding。  
下一步先做逻辑/文档对齐和 B 确认；烧录必须等 B 时序签核、寄存器/CDC 绑定确认和独占窗口批准。

## 2026-10-31 追加：M bit 实际板测

B 已烧 M bit，PC2 在 `192.168.137.101` 上完成：

- `VERSION 0xAC=0x504C4233`；初始 `STATUS=0x00FF0010`（READY=1）。
- `RESET_CACHE` + session 0/1/2 各 30 次 TEST：**90/90 通过**，ACK_DONE 全部通过。
- interleaved `0,1,2` 10 轮 × 3 session：**30/30 通过**。
- 错误注入：坏 CRC `ERR=3`、非法 session `ERR=4`、RESET 后 NaN Attention `ERR=5`，均 FAULT。
- **发现**：`CONTROL.SOFT_RESET=1` 未清 FAULT，STATUS 变 `0x00FF002E`（ERR=7），需 `pcie1-recover.sh`；跨 host 进程 C2H 仍需 recovery（errno 512）。
- 未做 Attention 数值/KV/性能；B bit 未测。

详见 `BOARD_TEST_20261031.md` 和同目录 JSON 证据。现场最后已 recovery 到 READY。
