# PC2 审阅：B v3 experimental bit（2026-10-31）

状态：**PC2 已接收并校验文件；未烧录、未上板、未改 binding。**  
证据目录：`docs/evidence/v3_bits_20261031/`。

## 1. 文件校验

| 文件 | 字节 | PC2 SHA256 | B 声明 | 结果 |
|---|---:|---|---|---|
| `v3_b_experimental.bit` | 4,850,323 | `c62146718eee00d26872f431534479a35827b274a8d8066ae9bdc2503a5b06f2` | `C62146718EEE00D26872F431534479A35827B274A8D8066AE9BDC2503A5B06F2` | 一致 |
| `v3_m_experimental.bit` | 4,850,323 | `25654eacc03949f131330ed3eda0ea370f1ade9095a199a9a7bd1d1dc3379fe4` | `25654EACC03949F131330ED3EDA0EA370F1ADE9095A199A9A7BD1D1DC3379FE4` | 一致 |
| `B_TO_PC2_V3_PROGRESS_20261031.md` | 2,985 | `866a726420c777b5de579cd200e5f80c13950c9d3b443d05dd800b18cf57c698` | — | 原文留存 |

文件是 Anlogic ASCII bitstream（header 以 `# Anlogic ASCII Bitstream` 开头）；B/M 两个文件大小相同但内容不同，hash 不同，符合不同策略 bit 的预期。

## 2. 与 PC2 v3/Plan B 的已对齐点

- B 接受 session 0/1/2 + control 255；v3 header session 在 offset 9；v2 拒绝。
- B 的粗 ERR 映射与 PC2 一致：`1=SEQ/position, 2=LAYER, 3=CRC, 4=SESSION, 5=PROTOCOL, 6=PAYLOAD_LEN, 7=INTERNAL`；`0=OK`。
- `DONE` 只有 `ACK_DONE` 清除；带内 RESET ACK 不置普通 DONE；`RESET_BUSY` 与 `READY` 互斥。与 `PLAN_B_STATUS_V3.md` 一致。
- 仿真层：M 三 session、position 0..32、tail 驱逐、全局 RESET 重放，B 报 104 帧；另 M 两 session 70 帧，其中 session0=PC1 v48 真实 NPU layer14 QKV，session1=人工变化。不是 B 的三条真实 NPU prompt。

## 3. 不能上板的硬限制

B 自己的报告已明确：

1. **时序未签核**：B setup WNS `+0.030 ns`、M hold WNS `+0.009 ns`，余量很小；两份报告仍有 no-clock 6、dummy-node 5、PLL/buffer 2 项 HIGH 检查，物理 CDC/约束未签核。
2. **控制寄存器未绑定**：逻辑候选 `0xA4` STATUS、`0xA8` CONTROL、`0xAC` VERSION（`0x504C4233`）；B 已确认 `0xA8` 与 vendor RAM[42] alias，`0x000810A8` 可修改同一 RAM，修复尚未进入 bit；alias/物理 BAR/节点/host 访问均未确认。
3. **B 当时未烧录/未上板**；104/70 帧是 M 的仿真，不是 B 的长序列或三条真实 NPU prompt 实板证据。
4. **无三条真实 NPU prompt**；两条 session 是人工变化输入。
5. `FAULT_CODE=0`、`LAST_SESSION=255`；PC2 只能依赖粗 `ERR`，不能依赖细 fault 定位。
6. 当前只检查 `(session,layer)` 内 position 顺序；没有跨层乱序检查。

因此 PC2 **没有烧录**；也不能把 `0xA4/0xA8/0xAC` 写成正式 binding 或直接用 host 访问。低 16 位译码/厂商 RAM 别名在写控制时可能误写，风险高于收益。

**烧录责任：B 负责。** 这个 bit 是 B 的构建产物，应由 B 在 B 的板/独占窗口完成烧录、VERSION/STATUS 只读验证、RESET/TEST 首轮，并提交烧录记录、实际寄存器行为、时序和 bit hash。PC2 只做接收校验、host/codec 对齐和 B 提供可访问窗口后的联合回归；PC2 不代替 B 烧写未签核 bit。

## 4. 建议的确认顺序

1. B 先给 timing closure：B setup/M hold 转正或明确书面风险接受；HIGH 时钟检查项关闭；CDC/约束签核。
2. B 确认寄存器：真实 offset、读写 API、alias 检查、写 mask、VERSION 读回、STATUS/CONTROL 是否同一 BAR；PC2 只做只读 VERSION 验证，确认前不写 CONTROL。
3. B 确认非有限 QKV 策略：PC2 接受“protocol reject”；建议 `ERR=5 PROTOCOL`、不修改 KV、不返回成功 C2H；`FAULT_CODE` 可为 0（B 当前实现），但 host 只看 `FAULT+ERR`。
4. 确认 layer 顺序：首版 endpoint 只保证 `(session,layer)` 内 position；host 按 **position p 的 layer0..29，再 p+1** 调度（具体例子写入 `MULTI_SESSION_INTERFACE.md` §4.1）；endpoint 不宣称跨层乱序检查，违例测试放 host 层。
5. 两条真实 NPU prompt 的逐层 QKV 和独立 golden 仍需补齐；否则只能做接口/隔离，不可做数值验收。
6. 以上完成后，**B 在 B 的板/独占窗口**烧录并做：备份当前 bit → 烧 B → VERSION/STATUS 只读 → RESET + 30 TEST → session0/1/2 小规模 → fault/reset → 再 M；失败按既有恢复流程处理，不把失败写成通过。PC2 只在 B 提供可访问窗口和烧录记录后做 host 联合回归，不替 B 烧写。

## 5. 请 B 回答

1. timing 何时签核？B setup WNS `+0.030 ns` / M hold WNS `+0.009 ns` 余量很小，HIGH 检查未清；继续修还是书面接受？
2. `0xA4/0xA8/0xAC` 是否最终地址？是否有 alias/低 16 位译码修复？host 读写 API 和写 mask 是什么？
3. 非有限 QKV 的精确 `ERR`/`FAULT_CODE` 和是否在写 KV 前拒绝？
4. 是否同意“endpoint 只检查 `(session,layer)` position；host 按每个 session 的 position p → layer0..29 → p+1 调度”？
5. 两条真实 NPU prompt 由 PC2 提供还是 B/PC1 已有？需要完整逐层 Q/K/V、token ID、hash 和顺序。
6. `FAULT_CODE`/`LAST_SESSION` 是否在下一版实现？若否，fault 定位靠什么日志？
7. 计数器是否仍为离线候选？`0xB0..0xBC` 是否可用？

## 6. PC2 当前状态

- 已接收/校验 bit，但**未烧录**；烧录由 B 负责。
- 已保留 B 原文和 bit hash；没有修改 v2/v3 正式 binding。
- 等 B 对第 4/5 节确认，并由 B 提交烧录/上板记录；在此之前 PC2 不进行板端 v3 访问。
