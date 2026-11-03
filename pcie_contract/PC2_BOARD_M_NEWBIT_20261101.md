# PC2 板测：新 M bit / resetfix（2026-11-01，实验性）

用户口述 B 已把新 M bit 烧上；PC2 未收到 resetfix `.bit` 文件，实际 hash 未独立校验。B 回复说 resetfix 尚未正式上板，因此当前板上的 bit 身份需要 B/用户确认。

## 1. 只读

串口 root `pcie1-recover.sh` 后：

```text
BAR0 0x5C = 0x56440013   (旧 v2 VERSION)
BAR0 0xA4 = 0x00000000   (候选 STATUS 为 0)
BAR0 0xA8 = 0x00000000   (初始)
BAR0 0xAC = 0x00000000   (候选 VERSION 为 0，不是 0x504C4233)
```

## 2. wire-only 通过

raw v3 RESET + TEST session0：

```text
RESET write 32/32; ACK session=255 layer=255 seq=1
TEST  write 1952/1952; ACK session=0 layer=0 pos=0 seq=2; payload match=True
```

## 3. 多帧/多 session 失败

第二帧 session=1 的 H2C write 阻塞到 deadline；第一帧 TEST 后没有可用的 `ACK_DONE` 清 DONE。候选 STATUS 为 0，无法等待 READY/DONE。

## 4. SOFT_RESET 探测失败

坏 CRC 后写候选 `CONTROL 0xA8=1`；随后 RESET write 阻塞到 deadline，未恢复 H2C。恢复后读 `0xA8=1` 仍然保留，说明写到了某个寄存器/RAM，但没有完成 resetfix 行为。  
可能原因：板上不是 resetfix、候选 CONTROL 地址/alias 不对、resetfix 的 STATUS/CONTROL 不在这些地址，或写到了 vendor RAM。B 之前已报告 `0xA8` 与 vendor RAM alias。

另：通过 `/dev/ANLOGIC-PCI0_user` 直接 `pread` 候选偏移导致进程段错误（RC=139），不要用 user 节点探测。

## 5. 结论

- 当前能证明：该 M bit 的 v3 RESET+单帧 TEST session0 wire 路径可用。
- 不能证明：ACK_DONE、多帧、多 session、SOFT_RESET/resetfix、FAULT 恢复、Attention/KV、性能、batch3。
- 当前候选 STATUS/VERSION 读 0，和旧 M v3（0x00FF0010/0x504C4233）不同；请 B 确认板上实际 bit hash 和真实寄存器映射。
- 现场已 recovery；`0xA8=1` 保留；无遗留 host 进程。

## 6. 请 B

1. 给实际 M bit 文件/完整 hash/烧录记录，确认是否为 `8291B813...` resetfix。
2. 给 resetfix 的真实 STATUS/CONTROL/VERSION 地址、节点、写 mask/WSTRB、alias 结论。
3. 解释 `0xA4/0xAC` 为 0、`0xA8=1` 后 H2C 不恢复；确认是否写到了 vendor RAM。
4. 在 binding/窗口确认前，PC2 不再写候选 CONTROL，也不把当前结果当 resetfix 通过。
