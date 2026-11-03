# B → PC2：v3 多 session 接口进展（草案）

日期：2026-10-31。本文是离线开发进展，未冻结协议，也不代表 v3 已上板。

1. 按你方 v3 草案，FPGA 原型把粗 ERR 调整为 1=SEQ/position、2=LAYER、3=CRC、4=SESSION、5=PROTOCOL、6=PAYLOAD_LEN、7=INTERNAL。多处同时错误时保留先发现的错误，FAULT 只在安全 SOFT_RESET 完成后清除；FAULT_CODE 暂为 0，LAST_SESSION 暂为 255。非有限 QKV 当前按 protocol 拒绝，尚需双方确认。
2. DONE 等 ACK_DONE 才清；带内 RESET ACK 不置普通 DONE；RESET_BUSY 与 READY 互斥。用厂商 `axil_anal`、候选寄存器层及 endpoint/CDC/guard 联合仿真了 RESET、TEST、ACK_DONE、坏 CRC 和软复位。
3. 控制寄存器当前仅作**本机工程候选**：逻辑 offset `0xA4` STATUS、`0xA8` CONTROL、`0xAC` VERSION，VERSION 代码候选 `0x504C4233`；现有顶层译码只检查低 16 位，写操作还会落到厂商寄存器 RAM。未确认别名、物理 BAR、节点或 host 访问；请不要据此改正式 binding 或上板访问。
4. 三个 session 的 B/M 交错 position 0–1 与独立软件逐帧对拍通过；M 两个 session 到 position 32 的 tail 驱逐/RESET 通过。测试用的是 PC/HF 固定输入与人工变换输入，不是三条实际 NPU prompt。
5. DDR AXI 模型分别延迟写响应、读响应时，guard 等待事务排空后复位；没有验证真实 DDR，也没有覆盖全部 AXI 超时/错误路径。
6. B/M 均补测写地址已接受但数据阻塞时的 reset。fault 和 ERR 的跨域路径已加延时锁存及延迟到达仿真，物理 CDC 和约束仍待签核。
7. 已使用 PC1 v48 真实 NPU layer14 QKV 补充 M 原型仿真：session0 p0–32 的每帧对照该包的 M golden，session1 为人工变换输入，覆盖首次 tail 驱逐与全局 RESET。总计 70 帧仿真通过，尚非新 bit 实板证据。
8. 三个 session 的 M 原型均已从 position 0 测至 32，每路首次 tail 驱逐和全局 RESET 后的重放通过，共 104 帧逐帧与 PC 软件参考一致；两条 session 为人工变化输入，未证明三路真实 NPU 输出。

待双方确认：每 session 跨 layer 顺序与违例测试、非有限 FP16 策略、寄存器版本标记/偏移/别名及读取方式，以及两条不同真实 NPU prompt 的逐层输入和独立 golden。当前只有 `(session,layer)` 内的位置顺序检查，不能声称已有跨层乱序检查。

完整综合及 P&R 现已完成，实验 bit 和独立报告见 `E:/KVmix/fpga/docs/V3_BATCH_BUILD_REPORT_20261031.md`。B：`C62146718EEE00D26872F431534479A35827B274A8D8066AE9BDC2503A5B06F2`；M 初版：`25654EACC03949F131330ED3EDA0EA370F1ADE9095A199A9A7BD1D1DC3379FE4`。两版 setup/hold 数值均为正，但 B setup 仅 30 ps、M hold 仅 9 ps，均仍有 HIGH 时钟检查项；物理 CDC、寄存器绑定、跨层规则未签核，未烧录或上板。不能拿以上结果当作 v3 板测或吞吐提升。
