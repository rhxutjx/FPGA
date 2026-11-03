# PC2 只读核对证据（2026-11-02）

对象：B v2 handoff 的 M dual GQA `044D...` 下载后窗口。  
操作：只读；**没有写 CONTROL，没有发 H2C**。

## 1. 时间/环境

| 项 | 值 |
|---|---|
| PC 本地时间 | 2026-11-02 21:44:28 +08:00 |
| 板端时间 | 2026-04-27 21:07:25 UTC（板钟不可靠） |
| 板端 uptime | 1:17 |
| BDF | `21:00.0 [1edb:abcd]` |
| 节点 | `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}` |
| 驱动服务 | `anlogic-sgdma active` |
| `poll_mode` | 1 |

**顺序说明：** 这是最后一次 `pcie1-recover.sh` 成功后的只读结果。B v2 已确认上次 JTAG 下载文件是 `044D...`，但没有给出精确下载时间/下载日志/板上回读；因此无法从 PC2 侧独立证明下载与本次只读的严格先后。若需要严格关联，请 B 提供下载时间/记录。

## 2. 实际访问方式

- 节点：`/dev/ANLOGIC-PCI0_control`，`os.open(O_RDWR)`。
- ioctl：`ANLOGIC_IOCR = 0x80107805`。
- 请求结构：`<HHIII>`，`bar_id, 0, offset, 0, 0`；读回 offset 12 的 u32。
- BAR 编号：`bar_id=0`（BAR0）和 `bar_id=1`（BAR1）。
- 偏移：
  - BAR0/BAR1：`0x5C, 0xA4, 0xA8, 0xAC, 0x800A4, 0x800A8, 0x800AC, 0xB0, 0xBC`
- 脚本 SHA256：
  - `read_v3_candidate_regs.py`：`4268a0972335ac3acd1626276c32094f81e28df9edd0bd95ac7b0784b38f950d`
  - `read_v3_bar1.py`：`8228f8aca14b16602bdbdd63abfadc5c27924b19c5786afbb605f2e20430b3b5`
- **WSTRB：无写操作，未使用。**

## 3. 原始返回值

```text
BAR0 0x5C    = 0x56440013
BAR0 0xA4    = 0x00000000
BAR0 0xA8    = 0x00000000
BAR0 0xAC    = 0x00000000
BAR0 0x800A4 = 0x00000000
BAR0 0x800A8 = 0x00000000
BAR0 0x800AC = 0x00000000
BAR0 0x8005C = 0x56440013

BAR1 0xA4    = 0xFFFFFFFF
BAR1 0xA8    = 0xFFFFFFFF
BAR1 0xAC    = 0xFFFFFFFF
BAR1 0xB0    = 0xFFFFFFFF
BAR1 0xBC    = 0xFFFFFFFF
```

完整原始文件：`docs/evidence/v3_resetfix_20261101/readonly_evidence_20261102.txt`

## 4. 判定

- `0x5C=0x56440013` 只是旧 v2 VERSION，不能标识 v3 应用寄存器。
- 期望 `VERSION=0x504C4233` 没有在 BAR0 `0xA4/0xAC` 或 `0x800A4/0x800AC` 出现。
- BAR1 对应偏移全部 `0xFFFFFFFF`。
- 只读核对 **失败**；无法确认 host `A4/A8/AC` → 内部 `0x000800A4/A8/AC`。

## 5. 下一步

仍需要 B 给/核实：

1. 精确 JTAG 下载记录（时间、方式、操作者、是否有板上回读）；
2. BAR0/BAR1 → 内部 `0x000800A4/A8/AC` 的实际地址转换；
3. 节点/API/WSTRB/mask/alias；
4. 或在新 bit 上只读确认 `0xAC=0x504C4233`、`0xA4=0x00FF0010`。

在 read-only 通过前，PC2 不写候选 CONTROL，不进入 resetfix/70 帧验收。
