# PC2 Plan B 状态定义（v3 DRAFT，2026-10-30）

状态：**DRAFT，未冻结、未上板、未改 v2 `contract.json`**  
用途：给 B 做 v3 endpoint 集成和可验证多 session bit 的**逻辑状态基线**。机器可读版本：`plan_b_status_v3.json`；位编解码：`plan_b_status_v3.py`；测试：`test_plan_b_status_v3.py`。  
边界：本文不猜 BAR 地址。`STATUS`/`CONTROL` 的具体 offset、读写节点、跨域稳定性和 busy/reset 时序必须由 B 对照新 RTL 确认；确认前地址为 **UNBOUND**。

## 1. 范围

- 首版 `max_sessions=3`，Attention/TEST session 0/1/2；全局 RESET 用 session 255。
- **单帧在途**；一个**全局** endpoint 状态，不做 per-session READY/FAULT/DONE。
- 全局 RESET 清除全部 session 的逻辑历史；不做 per-session reset。
- 状态是 v3 控制面，不进入 32B wire header，不改变 `contract_v3_session.json` 的帧格式。
- v2 endpoint 状态和 bit 不被本文件修改。

## 2. STATUS（32-bit，只读）

读法：现有已验证的 control/user 字符设备 32-bit pread；**无 read-clear 副作用**；host 至少读两次并要求快照一致。地址：**UNBOUND，B 确认**。

| bit | 名称 | 含义 |
|---:|---|---|
| 0 | DONE | ATTENTION/TEST 的 C2H payload 已稳定可读；保持到 host 写 `ACK_DONE` |
| 3:1 | ERR | 粗粒度错误：0=OK、1=SEQ、2=LAYER、3=CRC、4=SESSION、5=PROTOCOL/VERSION/OP/FLAGS/PADDING、6=PAYLOAD_LEN、7=INTERNAL/DDR/ENGINE/TIMEOUT/RESET |
| 4 | READY | 可接收新 H2C；仅当 `BUSY=0`、`DONE=0`、`FAULT=0`、`RESET_BUSY=0` 时为 1 |
| 5 | FAULT | 粘滞 fail-stop；只有 `SOFT_RESET` 完成才清除；FAULT=1 时禁止新 H2C |
| 6 | BUSY | 已接收一帧，处理中；host 不得写 H2C |
| 7 | RESET_BUSY | 控制面 `SOFT_RESET` 或带内 `RESET_CACHE` 进行中；READY=0 |
| 15:8 | FAULT_CODE | 细错误码；`FAULT=1` 时有效（见 §2.1） |
| 23:16 | LAST_SESSION | 最近完成/故障帧的原始 session_id；无/global reset 为 255；**首版可选** |
| 31:24 | reserved | 必须读 0 |

不变量：

- `BUSY` 与 `READY` 不同时为 1；`DONE`、`FAULT`、`RESET_BUSY` 也分别不得与 `READY` 同时为 1。
- 成功 `DONE` 时 `ERR=0`；`FAULT=1` 时 `ERR!=0`。
- `FAULT` 只能由 `SOFT_RESET` 清除；不能靠读状态、ACK_DONE 或下一帧清除。
- 状态读不得清除 DONE/FAULT；不能把“读到 DONE”当成 C2H 已传输完成。

### 2.1 FAULT_CODE

`0=NONE, 1=SEQ, 2=LAYER, 3=CRC, 4=SESSION, 5=VERSION, 6=OP, 7=PAYLOAD_LEN, 8=FLAGS, 9=PADDING/RESERVED, 10=DIRECTION, 11=DDR, 12=ENGINE, 13=TIMEOUT, 14=RESET_FAIL, 15=CONTROL_INVALID`。

`ERR` 是 3-bit 兼容粗分类；`FAULT_CODE` 是 v3 细分类。B 若不实现细分类，`FAULT_CODE=0` 且 `ERR` 仍必须非零；但 PC2 建议首版实现 `FAULT_CODE`，否则定位多 session/协议错误只能靠日志。

## 3. CONTROL（32-bit，只写）

地址：**UNBOUND，B 确认**。reserved 必须写 0；一次只写一个 action bit；self-clearing。

| bit | 名称 | 含义 |
|---:|---|---|
| 0 | SOFT_RESET | 应用逻辑复位：先 quiesce/停止当前操作，复位 H2C/C2H FIFO、parser、attention/KV FSM、DMA 应用状态；**不重置 PCIe HIP/BAR/link**；清除 FAULT；完成后 READY=1。它**不能替代**带内 `RESET_CACHE` |
| 1 | ABORT_BATCH | 可选：停止当前批并进入 FAULT；没有 per-session abort。首版可以只实现 SOFT_RESET，ABORT 置 reserved |
| 2 | ACK_DONE | self-clearing；host 已消费并校验 C2H 后清除 DONE；只允许 DONE=1 时写 |
| 31:3 | reserved | 必须写 0 |

host 规则：

- 写 `SOFT_RESET` 后必须 bounded poll `READY=1 && FAULT=0`；超时只能走 root PERST recovery，不能假设成功。
- `ACK_DONE` 后必须重新 poll READY，才能发下一帧。
- `SOFT_RESET` 完成后所有 session 历史无效；host 必须再发 `RESET_CACHE` 才能开始 Attention。

## 4. 全局状态机

```text
UNINIT --init--> READY
READY --H2C(ATTENTION/TEST) accepted--> BUSY
BUSY --C2H stable, ERR=0--> DONE
DONE --CONTROL.ACK_DONE--> READY
BUSY --protocol/transport/DDR/engine error--> FAULT
READY --RESET_CACHE accepted--> RESET_BUSY --32B ACK stable--> READY
READY/BUSY/DONE/FAULT --CONTROL.SOFT_RESET--> RESET_BUSY --application reset complete--> READY
```

- `FAULT` 没有自动出边；只能 `SOFT_RESET`。
- `RESET_BUSY` 从带内 `RESET_CACHE` 进入时有 32B C2H ACK；从控制面 `SOFT_RESET` 进入时没有 ACK，host 之后必须发 `RESET_CACHE`。
- `DONE` 只在 ATTENTION/TEST 成功时置位；RESET ACK 不置 DONE，host 在 RESET_BUSY 清除、READY=1 后读取 32B ACK。
- 首版没有 per-session 状态；所有 session 共享全局 READY/FAULT。

## 5. 启动/批次序列

```text
1. host 读 STATUS 两次，确认快照稳定
2. 若 FAULT=1 或 READY=0：
     CONTROL.SOFT_RESET=1
     bounded poll READY=1 && FAULT=0
     若超时：停止，root pcie1-recover.sh；不得继续 H2C
3. 仅在 READY=1 && BUSY=0 && DONE=0 && FAULT=0 时发送带内 RESET_CACHE
     session=255, layer=255, position=0, seq, payload=0
4. FPGA 置 RESET_BUSY、quiesce、清所有 (session,layer) 历史、M-store next_pos、
   缓存 valid 和响应状态；32B ACK 稳定后清 RESET_BUSY、置 READY=1
5. host 读正好 32B，校验 session=255/op/seq/CRC；ACK 成功后才从 position=0 开始
6. 任何 reset 都创建新的 batch identity；旧 batch/golden 失效
```

`RESET_BUSY` 期间 host 不写 H2C；`READY` 是唯一允许写 H2C 的条件。

## 6. 每帧序列

```text
1. 读 STATUS：READY=1, FAULT=0, BUSY=0, DONE=0, RESET_BUSY=0
2. 写完整一帧 H2C（ATTENTION/TEST 1952B，RESET 32B）；写错误立即本地 FAULT
3. bounded poll DONE=1 或 FAULT=1
4. FAULT=1：不把 C2H 当成功；进入 recovery
5. DONE=1：要求 ERR=0；读正好 1184B（ATTENTION/TEST）或 32B（RESET ACK）；
   校验 session/op/layer/position/seq、CRC 和 payload 语义
6. ATTENTION/TEST 成功后写 CONTROL.ACK_DONE；再 poll READY=1
7. 任何 mismatch：本地 FAULT；drain C2H；SOFT_RESET；RESET_CACHE；不自动重发
```

host 不能把 “DONE=1” 当作 C2H 已到 host；DONE 只表示 FPGA 侧 payload 稳定。

## 7. FAULT 恢复

```text
1. 立即停止 dispatch；不追加/重试部分完成的请求
2. 记录 STATUS、ERR、FAULT_CODE、LAST_SESSION、seq/session/layer/position、C2H drain 字节数
3. drain/隔离旧 C2H 到超时；旧帧不能作为新结果
4. 写 CONTROL.SOFT_RESET；bounded poll READY=1 && FAULT=0
5. 若 SOFT_RESET 不能恢复：停止，root pcie1-recover.sh（PERST# + unbind/rebind）；
   不得把未恢复写成成功
6. 恢复后重新 RESET_CACHE，重建整个批次；旧 batch/golden 全部失效
7. auto_retry=false、auto_resend=false、CPU/mock fallback=false
```

## 8. 超时与传输边界

- `deadline_enforced=false`；阻塞 H2C 没有应用层硬 deadline；驱动 `h2c_timeout=10s` 是现实上界，不能靠 Python 信号打断。
- 建议 host 默认（可调，不是硬件事实）：READY poll 2s、DONE poll 10s、C2H read 2s、reset poll 5s；全部 monotonic，超时 fail-stop。
- 每帧先查 READY 再写，避免进入阻塞写；READY 不稳定时不能写 H2C。
- 数据路径仍用现有 SGDMA H2C/C2H 字符设备；控制用现有已验证 user/control 32-bit pread/pwrite；保留驱动 IRQ；默认不用 raw mmap、不新增驱动。
- 单帧在途；DONE 后必须 ACK_DONE 才能下一帧；旧 C2H 必须隔离。

## 9. 计数器（候选，未确认）

B 的计数器目前只在离线 RTL，未经 BAR 读回。PC2 建议使用同一 user 控制字符设备做 32-bit 快照：

| 候选 offset | 访问 | 含义 |
|---:|---|---|
| `+0xB0` | W | COUNTER_SELECT（index） |
| `+0xB4` | R | COUNTER_VALUE_LO |
| `+0xB8` | R | COUNTER_VALUE_HI |
| `+0xBC` | W1 | COUNTER_SNAPSHOT / R STATUS |

索引：attention_frames、h2c_bytes、c2h_bytes、ddr_read_bytes、ddr_write_bytes、busy_cycles、fault_count（64-bit，各占 lo/hi），reset_count（32-bit）。  
**这些 offset 只是候选；B 必须先确认 BAR0 空闲、跨域稳定、写 1 快照语义和 reset 行为。确认前不得写入正式 contract，也不得在 host 使用。**

### 9.1 B 2026-11-01 的 alias 报告与 PC2 板测观察

B 的 RTL 仿真发现：内部 AXI-Lite `0x000800A8` 写 1 会同时触发 `CONTROL` 和 vendor RAM[42]；`0x000810A8` 写 `0xDEADBEEF` 可修改同一 RAM 单元。顶层只译码 `[15:8]==0` 和低 8 位，忽略 `[31:16]`；写需要完整 32-bit/WSTRB=0xF。该屏蔽修复尚未进入 bit，也没有解决高地址别名；这些地址从主机 PCIe BAR 是否可达仍未证明。**不要据此访问 `CONTROL`/`STATUS`，也不要改正式 binding。**

PC2 在 B 已烧 M、用户明确授权后，对 M experimental bit 做了板测：

- `VERSION 0xAC=0x504C4233`，初始 `STATUS 0xA4=0x00FF0010`（READY）。
- `CONTROL 0xA8` 的 `ACK_DONE`（bit2）在 90+30 次 TEST 中有效。
- `CONTROL.SOFT_RESET`（bit0）在坏 CRC 后**没有**清 FAULT；STATUS 变 `0x00FF002E`（FAULT=1, ERR=7 INTERNAL），必须 `pcie1-recover.sh`。
- 这些写入可能已经触发 vendor RAM alias；后续不再访问候选地址，B 修好并确认前不把结果当正式绑定。

## 10. B 集成验收清单

1. 实现并上板 `STATUS`/`CONTROL`；提供真实节点、offset、BAR、读写 API、位图和行为。
2. STATUS 无 read-clear；READY/DONE/BUSY/FAULT/RESET_BUSY 不变量成立。
3. `ACK_DONE` 清 DONE；`SOFT_RESET` 清 FAULT 并 quiesce；不重置 PCIe HIP/BAR/link。
4. RESET_CACHE 在无在途时 ACK；ACK 后旧 KV 逻辑不可读；新 batch 从 position=0 开始。
5. 非法 version/session/op/layer/position/CRC/payload/flags/padding 进入 FAULT，不返回成功。
6. 两个连续进程（不 PERST/不 rmmod）各跑 RESET + 30 TEST；再加 SOFT_RESET 版本。
7. 两 session 交错 + 边界 pos31/32/33/63/64 + 尾窗 + 重要层；各自匹配独立 golden。
8. 计数器快照与帧计数一致；B 记录 bit SHA256、TD/P&R、时序和烧录记录。
9. 提供 B/M bit、两条独立 prompt 的逐层 Q/K/V 输入和独立 golden；否则不能做多 session 验收。

## 11. 仍未冻结/仍需 B 回答

- `STATUS`/`CONTROL` 的物理 offset、节点、读写 API、跨域同步、busy 时 SOFT_RESET 策略。
- `DONE` 用 ACK_DONE 清除是否可实现；若不能，必须给等价的单帧完成/清除语义，不能靠读 C2H 隐式清。
- RESET_BUSY、RESET ACK 与 READY 的精确顺序；32B ACK 是否在 READY 前置稳定。
- `FAULT_CODE`/`LAST_SESSION` 首版是否实现；如果不实现，如何定位 fault 的 session/layer/position。
- 计数器候选 offset 是否空闲；快照是否 atomic。
- 多 session bit 的 B/M stride、资源、时序和 bit hash。

在这些确认前，PC2 只把本文件当 **DRAFT 逻辑基线**，不把它当已上板能力，也不在旧 v2 bit 上发送 v3 多 session 流量。
