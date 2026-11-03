# 三条独立 prompt QKV / batch3 调度（2026-11-01）

状态：**INTERIM / NOT M CLOSED-LOOP**。三条独立 prompt 的 Q/K/V 是 **实际 RK NPU post-RoPE**，但 attention/反馈路径是 **CPU F32 reference**，不是 M FPGA；不能当 M 输入/M golden/tail 证据。

## 1. 文件

| 文件 | 内容 |
|---|---|
| `qkv_three_prompt_20261101.tar.gz` | `manifest.json` + `qkv/` 下 3150 个 `.fp16.bin` |
| `manifest.json` | 3150 records、3 prompts、token IDs、每帧 SHA256 |
| `batch_schedule_3sessions_35x30.json` | session0/1/2 的 batch3 调度：1050 组、3150 行 |
| `capture_qkv_v50.py` | 生成脚本 |
| `validate_qkv_manifest.py` | 3150 文件逐字节/SHA/有限值校验 |
| `make_qkv_batch_schedule_generic.py` | 生成 batch 调度表 |
| `capture_3p.log` | 板端运行摘要 |

- QKV tar SHA256：`2e504ca2a308f6a1db34508f3cc850beca62cef615ec02c5ac29c81241855f00`
- 校验结果：`QKV_MANIFEST_OK`，3150 files verified，无非有限值。
- batch 调度：`3 sessions × 35 positions × 30 layers = 3150` 行，1050 组。

## 2. Prompts / 覆盖

| session | prompt | token 数 | token IDs SHA256 |
|---:|---|---:|---|
| 0 | Tim and the truck | 35 | `3ec4087f17c4c77ea279e2411583594dc2df445f51fb2cf770049df92ea98685` |
| 1 | Spot and his toy | 35 | `fdb237e165580a21dc11cb09589fba44df1e6a98bde96c8cf050111283e5e91a` |
| 2 | Mia in the kitchen | 35 | `97f7d14633e5772b85436c5651f4600994be6ec13593c13a7c92f4568f2f9175` |

- 位置 0..34（覆盖 32/33/34；不含生成 token 35）；层 0..29。
- 每个 prompt 35 token（含 BOS=0），tokenizer SHA `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`。
- 顺序：每个 session 的 `position p → layer0..29 → p+1`；同一 `(layer,position)` 下 session 可交错。
- batch 调度表的 rows 共享 `(position,layer)`，最多 3 行；endpoint 仍单帧在途，host 按行顺序发送；不是并行 FPGA Attention。

## 3. 关键边界

- 来源：**RK NPU linear（v38 INT8）+ CPU F32 reference attention feedback**；`fpga_used=false`、`m_bit_used=false`。
- 深层 QKV 的 hidden state 来自 CPU attention，不是 M；因此：
  - 可用于接口/顺序/独立参考、batch3 输入调度和 B 的审计；
  - **不能**用于 M tail/驱逐验收；
  - **不能**冒充 M golden 或“三条真实 NPU prompt 的 M 产出”。
- 真正 M closed-loop 需要 B 的 M bit（resetfix/签核版）和 host 反馈捕获；PC2 可再用同一三条 prompt 采集。
- 无性能/吞吐结论；无 Attention 数值对拍。

## 4. 复现

```sh
ulimit -n 8192
runuser -u kvdev -g kvdev -G users -G render -G video -- bash -c '
  ulimit -n 8192
  exec env PYTHONPATH=<v50-root> python3 capture_qkv_v50.py \
    --v50-root <v50-root> \
    --assets-host /home/kvdev/work_pc1_npu/text-v38.oySckQ/host \
    --output <new-dir> --prompts 1,2,3'
```

```sh
python3 validate_qkv_manifest.py <new-dir>
python3 make_qkv_batch_schedule_generic.py <new-dir>
```
