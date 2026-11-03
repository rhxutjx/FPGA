# 更正：候选寄存器板测不能证明 resetfix 失败

日期：2026-11-01  
依据：B 的 `V3_ACCEPTANCE_FIXES_20261101.md`、`v3_build_verification.json`。

## 事实

- `v3_m_experimental.bit`（SHA256 `8291B813...35AAE4`）文件已收到，是 B 的 M resetfix 候选；构建报告为 M、setup/hold `+0.069/+0.012 ns`、STA coverage 99.50%，仍有 no-clock/dummy-node/PLL HIGH，未签核。
- B 的报告明确：`0x000800A4/A8/AC` 是**内部 AXI-Lite 候选地址**，尚未证明能从主机 PCIe BAR0 逻辑偏移 `0xA4/A8/AC` 到达；BAR 映射、host 访问和写 mask 仍未冻结。
- 因此 PC2 之前对 host BAR0 `0xA4/0xA8/0xAC` 和 `0x800A4/0x800A8/0x800AAC` 的读写**不能用于判断 resetfix 是否生效**：
  - `0xA4/0xAC=0` 不代表 bit 没有 STATUS/VERSION；
  - `0xA8/0x800A8` 写后仍为同一值，可能只是 vendor RAM/错误映射；
  - ACK_DONE/SOFT_RESET 失败只说明 host 候选映射不可用，不是 resetfix RTL 结论。
- 本轮唯一有效结论：**wire-only 单帧 v3 RESET + TEST session0 通过**；多帧/多 session/ACK_DONE/SOFT_RESET 在候选 host 映射下不可测。

## 更正后的结论

- 不把旧的“新 M bit resetfix 失败/bit 不对”当结论；应改为：**host 候选寄存器映射未绑定，候选读写无效。**
- B 需要给 PCIe BAR → 内部 AXI-Lite 的实际映射/访问路径；确认前 PC2 不再访问 `0xA4/0xA8/0xAC/0xB0..0xBC`，也不改正式 binding。
- 板子已 recovery；候选 `0xA8/0x800A8` 残留值来自无效写，不能当控制状态。

## 仍有效的证据

- 文件 hash 8291 与 B 一致；
- raw v3 RESET/TEST 单帧通过；
- B 的构建报告：M setup/hold +0.069/+0.012，仍非时序/CDC 签核。
