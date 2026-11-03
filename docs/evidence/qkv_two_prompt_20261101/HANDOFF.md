# 两条独立 prompt QKV handoff（2026-11-01）

状态：**INTERIM / NOT M CLOSED-LOOP**。这是 PC2 能给 B 的两条独立 prompt 逐层 QKV；Q/K/V 是 **实际 RK NPU post-RoPE**，但 attention/反馈路径是 **CPU F32 reference**，不是 M FPGA。不能把它标成 M 输入或 M golden。

## 1. 文件

```text
qkv_two_prompt_20261101.tar.gz   # manifest.json + qkv/ 下 2100 个 .fp16.bin
manifest.json                    # 2100 records、token IDs、每帧 SHA256
capture_two_prompt_qkv_v50.py    # 生成脚本
validate_qkv_manifest.py         # 2100 文件逐字节/SHA/有限值校验
capture_d.log                    # 板端运行日志
```

- QKV tar SHA256：`a7a78475d2b77efbbc478708dbf857264f8a119d6a47d5bebdbd3cb5c8ee05c6`
- manifest `summary_sha256`：`53e8ea63a6666773b169e859771c6ba7616fccda24d42cfbf088c3b1c14d8cd0`
- 校验结果：`QKV_MANIFEST_OK`，2100 files verified，无非有限值。
- `batch_schedule_2sessions_35x30.json`：把两条 prompt 映射到 session0/1，按 `position p → layer0..29` 分组；1050 组、2100 行、batch_size=2。只是 host/NPU 行分组；v3 endpoint 仍单帧在途，不是并行 FPGA Attention。

## 2. 覆盖范围

| 项 | 值 |
|---|---|
| 模型 | SmolLM-135M，v38 INT8 assets |
| 线性 | RKNN INT8 MatMul，M=1 |
| attention | CPU F32 reference（`host.reference.cpu_reference.CPUAttention`） |
| FPGA/M bit | **未使用** |
| prompts | 2 条独立 TinyStories：`Tim and the truck`、`Spot and his toy` |
| token 数 | 每条 35（含 BOS=0） |
| 位置 | 0..34（覆盖 32/33/34；不含生成 token 35） |
| 层 | 0..29 |
| 帧数 | 2 × 35 × 30 = **2100** |
| 顺序 | 每个 prompt 内 position-major、layer-minor（p0/l0..l29，再 p1） |
| QKV | 1920B：Q[9,64] post-RoPE、K[3,64] post-RoPE、V[3,64]；head-major；FP16 LE |

两条 prompt 的 token IDs 和 SHA256 在 `manifest.json` 的 `prompts`；第一帧从 BOS=0 开始。

## 3. 关键边界（必须写进 B 的记录）

- 这是 **RK NPU post-RoPE QKV + CPU reference attention 反馈**。
- 不是 M FPGA closed-loop；深层 QKV 的 hidden state 来自 CPU attention，不是 M 输出。**不能用于 M tail/驱逐验收，也不能冒充 M golden。**
- B 可以：
  - 用这两条独立 prompt 的 QKV 做接口/顺序/独立 golden 生成；
  - 用它做 PC/HF reference 对拍；
  - 但不能把它当“三条真实 NPU prompt 的 M 产出”。
- 若 B 需要 **真正 M 输入**，需要 B 的 M bit（v48 或后续签核版）做 closed-loop；PC2 再用同一两条 prompt 捕获 M 反馈后的 QKV。
- 没有生成 token 35；没有 KV 压缩/驱逐状态；没有性能结论。

## 4. 复现

板端（需要 NPU video 权限；不是 FPGA）：

```sh
ulimit -n 8192
runuser -u kvdev -g kvdev -G users -G render -G video -- bash -c '
  ulimit -n 8192
  exec env PYTHONPATH=<v50-root> python3 capture_two_prompt_qkv_v50.py \
    --v50-root <v50-root> \
    --assets-host /home/kvdev/work_pc1_npu/text-v38.oySckQ/host \
    --output <new-output-dir> --prompts 1,2'
```

生成后：

```sh
python3 validate_qkv_manifest.py <output-dir>
```

## 5. 来源/限制

- 生成脚本基于 v50 的 `RuntimeAssets`/`RKNNLinearEngine`/`InferenceRuntime` 和 `CPUReferenceWithVectors`；实际 NPU 线性，CPU attention。
- tokenizer SHA256：`9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`。
- 板卡时钟错误；文件日期用 PC 日期。
- 未访问 B 的 M bit 寄存器；未改 v2/v3 binding。
