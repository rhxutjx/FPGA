# NPU batch=2/3 证据（PC2，2026-10-30）

状态：**NPU linear-only 实测通过；不是完整模型、不是 FPGA/PCIe 端到端。**  
来源板卡：RK3576 EVB1，SSH `192.168.138.101`（`end0` down；`end1` 可用），`kvdev`。  
板端原始目录：`/home/kvdev/work_pc2_pcie/batch_probe_20261030/`。

## 文件

| 文件 | 用途 |
|---|---|
| `npu_linear_batch_summary.json` | 211 个实际 v38 linear 权重的机器可读原始汇总；`status=PASS` |
| `batch_matmul_noc.py` | PC2 的 RKNN MatMul 参数化 wrapper（`M=batch`）；未改 PC1 原文 |
| `npu_linear_batch.py` | 逐权重 batch=1/2/3 对照 benchmark |
| `probe_batch.py` / `probe_batch_noc.py` | shape 级探针 |
| `probe_shapes_noc.py` | shape 级 batch 探针 |
| `batch_matmul.py` | 早期探针，未用作生产 batch 路径 |
| `run_linear_batch.sh` | 板端运行入口；`runuser ... -G video` |
| `weights_and_runtime.sha256` | 211 个 v38 INT8 权重逐一 SHA256 + `librknnrt.so` / manifest hash |
| `../../NPU_BATCH_CAPABILITY_20261030.md` | 完整报告、边界和结论 |

## 环境/版本

- RKNN runtime：`/usr/lib/librknnrt.so`，API `2.3.0 (c949ad889d@2024-11-07T11:35:33)`，driver `0.9.8`。
- SDK：`/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.vendor/rknn`。
- 生产参考 wrapper：`host/tests/_rknn_matmul_no_c_init_v10.py`（原始 `M=1`）；本目录 `batch_matmul_noc.py` 是 PC2 的 `M` 参数化副本。
- 权重：`host/.fixtures/forward_v34/fixtures` 的实际 v38 INT8 权重；211 个权重 manifest SHA256：
  `dde1079de74d896d2c2b7db529835f0c079abcb14eb9b7dae4badb449cd4d2d0`。
- `librknnrt.so` SHA256：
  `73993ed4b440460825f21611731564503cc1d5a0c123746477da6cd574f34885`。

## 运行

```sh
ssh kvdev@192.168.138.101
cd /home/kvdev/work_pc2_pcie/batch_probe_20261030
./run_linear_batch.sh
```

脚本使用 `runuser -u kvdev -g kvdev -G users -G render -G video`；`kvdev` 本身不在 `video` 组。

## 结果边界

- 211/211 个权重的 batch2/3 输出与逐行 batch1 NPU 输出逐位一致。
- NPU linear-only 折算：batch1 `17.74`、batch2 `33.92`、batch3 `49.95` tokens/s（只含 linear step，不含 Attention/PCIe/host/生成）。
- 不包含：FPGA Attention、KV 多 session、PCIe H2C/C2H、host 调度、真实文本 tokens/s。
- 原始 console 输出没有单独保存；`npu_linear_batch_summary.json` 是脚本写出的机器可读原始结果。若要二次复核，按上面命令重跑并保存 stdout/stderr。
- 本证据不改变 v2/v3 wire contract，也不证明 B 的 bit。
