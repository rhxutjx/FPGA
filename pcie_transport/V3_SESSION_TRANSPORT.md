# v3 session transport / batch scheduler（offline，2026-11-01）

状态：**HOST-SIDE DRAFT；无 BAR binding、无硬件测试。**  
文件：`pcie_transport/v3_transport.py`、`pcie_transport/tests/test_v3_transport.py`。  
测试：`python -m unittest pcie_transport.tests.test_v3_transport -v`，8/8 通过。

## 1. 它解决什么

- 把 v3 wire codec、Plan B READY/DONE/FAULT/ACK_DONE、global RESET 和单帧在途封装成可复用 host transport。
- 明确 **session 是 KV 上下文，batch 是 host/NPU 行分组**；endpoint 仍是单帧在途。
- `SessionBatchScheduler` 可以把同 `(layer, position)` 的最多 3 个 session 组成 batch 行；它只按行顺序发送，**不声称并行 FPGA Attention**。

## 2. API

```python
transport = V3Transport(device, status, timeout_s=5.0, start_seq=1)
transport.reset_all()                 # global RESET -> 32B ACK
transport.test(0, payload_1920)       # TEST -> 1184B C2H, compare first 1152
transport.attention(1, layer, pos, qkv_1920)
```

`device` 提供 `write/read_exact/flush_queues`；`status` 提供 `poll_ready/poll_done/ack_done/soft_reset`。  
`PlanBStatusController(read_status, write_control)` 可把实际的 32-bit BAR 读写函数接进来；地址由 binding 提供，不在模块里硬编码。

批量门面：

```python
scheduler = SessionBatchScheduler(transport, max_batch=3)
items = [BatchItem(0, layer, pos, qkv0),
         BatchItem(1, layer, pos, qkv1),
         BatchItem(2, layer, pos, qkv2)]
results = scheduler.attention_batch(items)
```

## 3. 保证

- 全局 RESET 前拒绝 Attention；TEST 也要求 READY。
- `seq` 单调、不复用；单帧在途；短写/短读/错回显/FAULT 全部 fail-stop。
- `DONE` 后读 C2H，再 `ACK_DONE`，再等 READY。
- `recover()` 只做 C2H 隔离 + `SOFT_RESET` + READY；之后仍需 global RESET。
- batch 行必须是不同 session、相同 `(layer,position)`；不超过 3 行。

## 4. 边界

- 没有 BAR offset/节点；`PlanBStatusController` 的读写函数必须来自冻结 binding。
- `SOFT_RESET` 在当前 M 实验 bit 上未清 FAULT（见板测）；模块只暴露接口，不掩盖该问题。
- 没有实现 NPU `M=2/3` 的模型级行堆叠；`SessionBatchScheduler` 只是 host 行调度门面。
- 没有端到端 tokens/s；没有 Attention 数值 golden。
