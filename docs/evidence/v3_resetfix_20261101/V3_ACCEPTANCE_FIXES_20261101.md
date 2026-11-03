# v3 上板前问题与寄存器原型改进记录

日期：2026-11-01。状态：**离线 RTL 原型与定向仿真，尚未生成新 bit、未上板。**

## 为什么旧 experimental bit 还不能作为正式验收版

1. **内部寄存器写冲突**：旧版候选 CONTROL 使用内部地址低位译码。仿真证明向 `0x000800A8` 写控制字时，同一笔写入也会改写厂商 `axil_anal` 的 RAM；候选译码还忽略部分高位，可能从别名触发控制。
2. **读响应背压问题**：新定向仿真复现，当读响应的 `RVALID=1` 而 `RREADY=0` 时，旧 overlay 的 `rsel` 下一拍提前变为 0。当前 top 的读数据 mux 因此可能在响应尚未被接收时切回厂商数据；是否发生取决于实际总线时序，不能认为已经在板上复现。
3. **PCIe 地址绑定未知**：`0x000800A8` 是 RTL 仿真中使用的内部 AXI-Lite 候选地址，尚未证明 PC2 的 BAR0 逻辑偏移 `0xA8` 一定到达此处；VERSION 与 STATUS 同理。因此不能直接把原型当作团队已冻结的 BAR 映射。
4. **时序/跨时钟尚未签核**：旧 B 的 setup/hold WNS 分别为 +0.030/+0.020 ns；旧 M 为 +0.041/+0.009 ns，数值为正但余量非常小。M 的 STA coverage 为 99.50%，报告仍有 6 类 no-clock、5 类 dummy-node 和 2 条 PLL 频率不匹配 HIGH。实际 no-clock 名称包括相机配置及 PCIe `user_link_up`；dummy-node 涉 DDR PHY、DSP 等模型，不能一概断定为真实故障或无害。PLL 报告将 PCIe 两个时钟的约束频率 125 MHz 与器件设置 62.5 MHz 标为不一致，须结合厂商 IP 和真实时钟核对，不能仅靠删改告警签核。跨时钟 FIFO 和复位也需检查。
5. **仿真与板测覆盖不同**：PC2 已对旧 M bit 板测 RESET、90/90 TEST、30/30 交错 TEST 及坏 CRC、非法 session、NaN 故障；坏 CRC 后 SOFT_RESET 未恢复，报 ERR=7。B bit 尚未板测；M 尚未证明板上 Attention 数值、三路 KV 隔离和系统吞吐。

这些问题不代表旧 bit 一定无法工作；含义是目前证据不足以保证它对团队的地址、数据和时序要求都可靠。实验性验证与正式验收应分开记录。

## 本次隔离原型做了什么

目录：`E:/KVmix/batch_fpga_prototype_20261030/bar_stall_experiment_20261101/`。由 `prepare_bar_exact_experiment.py` 和 `prepare_bar_stall_experiment.py` 从旧文件生成，不覆盖旧工程或 bit。

- 在内部候选 `0x000800A4/A8/AC` 上使用完整地址译码；只在内部精确 CONTROL 地址抑制厂商 RAM 的同笔写入。其他高地址/厂商 bank 继续遵循厂商 RAM 原行为；该 RAM 自身跨 bank 的地址别名并未宣称消除。
- 在原型 overlay 增加响应握手输入，使读选择保持至 `RVALID && RREADY`；响应消费与下一笔地址同时握手时切换到新响应。
- 修改厂商 slave 的原型副本：有未接收读响应时不再接收新的读地址，且只在读地址握手时锁存 RAM 输出，避免等待期间数据随地址变化。
- 这些变更涉及厂商 slave 与 top 连线；**尚未合并 TD 工程**。固定内部地址只是验证假设，必须先确认实际 PCIe 映射，不能凭此更新 host 的正式 binding。

## 验证证据与边界

- `bar_exact_experiment_20261101/v3_bar_exact.log`：复现旧读选择在背压下提前退出；同时测试精确译码隔离。
- `bar_stall_experiment_20261101/v3_bar_stall.log`：精确地址与其他地址写入、overlay 和 vendor RAM 的读响应背压、消费旧响应同时接受新地址，定向仿真通过。
- `bar_stall_experiment_20261101/results/v3_control_cdc.log`：候选寄存器 + reset guard + endpoint/CDC 组合的 RESET/TEST/DONE、半帧软复位、CRC 故障和恢复仿真通过；该集成用例的响应端始终 ready，背压由上面的独立用例测试。它不是物理 CDC 签核或真实 PCIe/DDR 板测。
- `unit_manifest.json` 和 `results/manifest_subset.json` 记录测试源哈希和结果。当前 Windows Icarus 编译器写出 VVP 后返回 `0xC0000005`；VVP 独立执行返回 0 并输出通过标记。由于编译器异常，**不能称为干净工具链通过**，须用正常退出的工具复测。
- `ddr_monitor_experiment_20261101/source_comparison.json`：仿真所用与 TD 工程的主要模块分别比较 B 22 项、M 23 项，SHA256 全部一致；顶层 DDR 监控是测试台按同一逻辑重建，不是整个物理顶层的逐字节比较。

## PC2 SOFT_RESET/ERR=7：复现及修复候选

PC2 的新包记录旧 M bit 在坏 CRC 后写 SOFT_RESET，`STATUS=0x00FF002E`。在包含顶层 DDR-loss 监控行为的 RTL 组合仿真中，分别在“半帧后软复位”和“坏 CRC 后软复位”复现同样的状态：软件复位使 `v3_endpoint_cdc` 的 `bridge_arst_n` 清除 `ddr_ready_usr`，顶层此前已重新置位 `ddr_was_ready`，因此锁存 `ddr_lost`；复位解除后反馈为 ERR=7。此前组合测试没有模拟顶层这段监控，因此漏掉了该情形。**这说明逻辑上存在能够产生相同症状的问题，不能单凭仿真证明板上唯一根因。**

候选改动是：DDR 物理校准就绪信号使用不受应用软复位影响、在 PCIe user 时钟下独立两级同步的副本进行掉线检测；业务 READY 仍依赖原 bridge-ready 等条件。`ddr_monitor_experiment_20261101/bridge/v3_control_cdc.log` 和 `bridge_crc/v3_control_cdc.log` 分别记录两种旧监控复现；`physical/v3_control_cdc.log`（M）和 `physical_b/v3_control_cdc.log`（B）记录替换监控后 RESET/TEST、坏 CRC 后复位以及真实 DDR ready 拉低的 fail-stop 定向测试通过。B 对应编译器退出码 0；M 本轮编译器仍出现上述退出异常，物理 CDC/故障时序和真实 DDR 还需验证。

此前启动的 `batch_v3_b_barfix_20261101` / `batch_v3_m_barfix_20261101` 构建**只有寄存器原型，并未包含该 DDR-loss 监控修复**；它们即使生成 bit 也只用于评估该次综合/时序，不能当作已修复 PC2 报告的版本。

该两份寄存器原型的完整布线已结束：B setup/hold WNS 为 +0.014/+0.020 ns、STA coverage 99.43%；M 为 +0.039/+0.020 ns、STA coverage 99.50%。余量仍小，具体 HIGH 项和 CDC 尚未签核；此结果不能替代下述 resetfix 工程自己的布线报告。

已另建 `batch_v3_b_resetfix_20261101` / `batch_v3_m_resetfix_20261101` 隔离工程，将两项寄存器修复候选与上述物理 DDR 就绪监控候选一起接入顶层。B、M 均已完成完整综合、布局布线并生成实验 bit；以各工程 `synth_v3.log`、`physical_v3.log`、最终 timing/area 和 `v3_build_verification.json` 为依据。这些是**候选实验版**，BAR、时序/CDC 和板端验证尚未关闭。

| 模式 | setup/hold WNS | STA coverage | slice | ERAM | DSP |
| --- | --- | --- | --- | --- | --- |
| B | +0.073/+0.020 ns | 99.43% | 37137/64320 | 156/272 | 5/240 |
| M | +0.069/+0.012 ns | 99.50% | 40999/64320 | 157/272 | 23/240 |

- B：`E:/KVmix/batch_v3_b_resetfix_20261101/v3_b_experimental.bit`；SHA256 `D24B109D6E61CD180CBEB763F44F0E29393632521C8739BDC1C55B6A2F2F52AB`。
- M：`E:/KVmix/batch_v3_m_resetfix_20261101/v3_m_experimental.bit`；SHA256 `8291B81385E3705D3B8887EE9DA544712BC55F598992AB0AB53737800035AAE4`。

两版均仍有 6 no-clock、5 dummy-node、2 PLL/clock buffer HIGH 检查，源文件快照复核无变化。setup/hold 虽为正但非常小，不能简单归因于某次 RTL 修改或视为板上稳定性证明。**这仍不是协议绑定、CDC 或板端签核。**

## 接下来

1. 查清 PCIe BAR 到内部 AXI-Lite 的地址变换，与 PC2 冻结寄存器和访问语义；审查 vendor slave 的读写握手与复位状态，再把原型连入隔离版 TD 工程。
2. 用正常退出的仿真工具重跑负例、背压、读写并发、异常/reset、B/M 端到端及 session 交错测试；必要时补充新用例。
3. 对两种模式分别做完整综合与布局布线，重新审查资源、setup/hold、时钟定义、未约束路径及 CDC；不能把局部正 WNS 直接当作时序签核。
4. 在版本、哈希及双方窗口确认后，分阶段进行 DDR、RESET/OP_TEST、多 session、真实 NPU 向量和系统吞吐测试。上板使用哪一版，以完整工程和报告为准。
