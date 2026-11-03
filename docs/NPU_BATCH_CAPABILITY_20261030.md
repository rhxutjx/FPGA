# NPU batch=2/3 能力报告（RK3576）

日期：2026-10-30
执行：PC2 接管，板卡 RK3576 EVB1（`linaro-alip`，kernel 6.1.99），串口 root + SSH `192.168.138.101`
范围：**RKNN MatMul 算子级能力**，不是完整模型、不是 FPGA Attention、不是 PCIe/H2C
结论：**当前 RKNN MatMul 生产 wrapper 支持 batch=2/3；所有 SmolLM linear shape 的 batch 输出与单行 NPU 输出逐位一致。**

## 1. 环境与代码路径

- RKNN runtime：`/usr/lib/librknnrt.so`，API `2.3.0 (c949ad889d@2024-11-07T11:35:33)`，driver `0.9.8`
- SDK：`/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.vendor/rknn`
- 生产绑定：`host/tests/_rknn_matmul_no_c_init_v10.py`
  - 原始代码 `M=1`，A `[1,K]`，C `[1,N]`
  - 本次只在 **PC2 副本**把 `M` 参数化，未改 PC1 原文件
- 对照：`host/backends/rknn_matmul.py` 是实验 binding；它在本 probe 下出现 CPU/单行不一致，**不应作为生产 batch 路径**
- 板端脚本目录：`/home/kvdev/work_pc2_pcie/batch_probe_20261030/`

## 2. 方法

- 输入：INT8 `A[M,K]`，INT8 `B[K,N]`，输出 INT32 `C[M,N]`
- 每个 shape：
  1. 对每一行单独创建 batch=1 context，得到单行 NPU reference；
  2. 创建 batch=2/3 context，一次 `rknn_matmul_run`；
  3. 逐行比较 batch 输出与单行 NPU 输出；
  4. 对 576×576 额外与纯 Python INT8 点积比较。
- 随机值：`-127..127`；K/N 使用实际 SmolLM linear shape。
- 计时包含 input copy/sync、input bind、`run_api`、output sync；不是纯 NPU 周期。

## 3. 结果

| shape (K×N) | 对应 | batch=2 逐位 | batch=3 逐位 | batch=2 step | batch=3 step | batch=3 run_api |
|---|---|---|---:|---:|---:|---:|
| 576×576 | Q / O | **PASS** | **PASS** | 287.8 us | 276.7 us | 213.4 us |
| 576×192 | K / V | **PASS** | **PASS** | 168.3 us | 165.9 us | 123.2 us |
| 576×1536 | gate/up | **PASS** | **PASS** | 304.6 us | 248.0 us | 182.7 us |
| 1536×576 | down | **PASS** | **PASS** | 340.0 us | 340.7 us | 280.9 us |
| 576×49152 | LM head | **PASS** | **PASS** | 7957.1 us | 8235.6 us | 7735.8 us |

- 576×576 的 CPU INT8 点积：单行和 batch2/3 都是 **0 mismatch、max abs diff 0**。
- 所有 shape 的 batch2/3 都与单行 NPU reference **逐位一致**。
- `attrs` 返回 shape 正确：A `[M,K]`、B `[K,N]`、C `[M,N]`。
- 创建/装载开销（一次性）：
  - 576×576 setup ≈ 2.4 ms；
  - 576×1536/1536×576 setup ≈ 5 ms；
  - 576×49152 setup ≈ **555 ms**（B 28,311,552 B 上传），create ≈ 39 ms。
  - LM head 的权重装载是 context 级固定开销，211 个 context 的完整模型要计入。

## 3.5 全 211 个 linear 权重（实际 v38 INT8 权重）

用 `text-v38.oySckQ/host/.fixtures/forward_v34/fixtures` 的实际权重，逐个跑
30 层 × (q/k/v/o/gate/up/down) + head，共 **211 个 linear**；每项用 3 个随机
INT8 A 行，先做 3 次 batch=1 NPU 参考，再做 batch=2/3；比较逐位输出。

| tag | shape | 权重数 | batch2 逐位 | batch3 逐位 | batch2 总 step | batch3 总 step |
|---|---|---:|---:|---:|---:|---:|
| q | 576×576 | 30 | 30/30 | 30/30 | 5,929 µs | 6,488 µs |
| k | 576×192 | 30 | 30/30 | 30/30 | 5,274 µs | 5,300 µs |
| v | 576×192 | 30 | 30/30 | 30/30 | 5,113 µs | 5,106 µs |
| o | 576×576 | 30 | 30/30 | 30/30 | 6,445 µs | 6,648 µs |
| gate | 576×1536 | 30 | 30/30 | 30/30 | 9,287 µs | 9,397 µs |
| up | 576×1536 | 30 | 30/30 | 30/30 | 9,401 µs | 9,557 µs |
| down | 1536×576 | 30 | 30/30 | 30/30 | 9,487 µs | 9,424 µs |
| head | 576×49152 | 1 | 1/1 | 1/1 | 8,017 µs | 8,142 µs |

汇总（step 含 input copy/sync、bind、run、output sync；不是纯 NPU 周期）：

| 项 | batch=1 | batch=2 | batch=3 |
|---|---:|---:|---:|
| 全部 linear step | 169,099 µs（633 次单行） | 58,953 µs（211 次） | 60,061 µs（211 次） |
| 折算每 token（同一模型） | **56.37 ms** | **29.48 ms** | **20.02 ms** |
| NPU linear-only tokens/s | 17.74 | 33.92 | **49.95** |
| 相对 batch1 | 1.00× | 1.91× | **2.82×** |

- **211/211 个权重的 batch2/3 输出与单行 NPU 输出逐位一致。**
- 这批权重是实际 v38 INT8 权重，不是合成 B；A 是随机 INT8 行，只验证 batch 语义与数值一致性，不代表模型质量。
- LM head 的 576×49152 context setup 约 555 ms；batch step 表中不含这次权重装载。
- 这是 **NPU linear-only** 的放大，不是整机 tokens/s；整机还要加 FPGA Attention、PCIe、host 调度和序列依赖。

## 4. 结论

1. **NPU MatMul 的批处理不是 Python 循环**：一次 `rknn_matmul_run` 使用 `M=2/3`，attrs/C shape 都是 `[M,N]`。
2. **数值上有效**：batch2/3 对每个实际 linear shape 都与单行 NPU 输出逐位一致；576×576 还与 CPU INT8 点积一致。
3. **生产 wrapper 需要参数化 M**：当前 `RKNNLinearEngine.run(inputs)` 是单向量；要支持 batch 必须改：
   - `M=batch`；
   - A `[batch,K]`、C `[batch,N]`；
   - input `batch*K`、output `batch*N*4`；
   - `RKNNLinearEngine` 的输入/输出和上层 model 调度。
4. **不要使用 `host/backends/rknn_matmul.py` 作为 batch 依据**：它的实验布局在本 probe 下单行/CPU 就不一致；生产绑定是 `_rknn_matmul_no_c_init_v10.py`。
5. **batch=2/3 的完整模型吞吐仍未证明**：本报告只证明 NPU MatMul 算子和实际 shape 支持；host 多序列调度、FPGA 多 session、PCIe、整机 tokens/s 仍需下一步。

## 5. 建议给 PC1 的接口

- `RKNNLinearEngine(sdk, k, n, weights, batch=M)`；
- `run(inputs: bytes length M*K) -> (tuple length M*N, timing)`；
- 每个 session 的 hidden state 保持 `[M,K]` 行优先；
- 211 个 context 的权重复用；batch 只改变 M，不重复上传权重；
- 测试先跑 Q/O/K/V/gate/up/down，再跑 LM head 和完整 30 层；
- 每个序列的输出仍需与独立单序列 golden 对拍，batch 不得改变归约顺序/量化 scale。

## 6. 边界

- 这是 **算子级 microbenchmark**，不是完整 SmolLM-135M batch 推理。
- 随机 B/A，不是正式模型权重；只验证 batch 语义/数值一致性，不代表模型质量。
- 计时包含 host copy/sync，不是 NPU 纯计算周期，也不是 tokens/s。
- LM head 的 setup 555 ms 是 context 装载；211 context 的完整模型需要单独测内存/时间。
- 当前板卡 bit/FPGA 未参与；`poll_mode` 与本报告无关。
- 原始探针输出在板端目录；本报告没有改 PC1 原文件、没有改 bit、没有上 H2C。
