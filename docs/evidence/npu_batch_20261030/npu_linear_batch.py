#!/usr/bin/env python3
"""Full SmolLM-135M linear-shape NPU batch benchmark using actual v38 INT8 weights.

Compares batch=2/3 against per-row batch=1 NPU outputs for every layer weight.
This is NPU-only: no model forward, no FPGA, no PCIe, no H2C.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_matmul_noc import RKNNMatmul

SDK = Path("/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.vendor/rknn")
FIX = Path("/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.fixtures/forward_v34/fixtures")
LAYERS = 30
LAYER_SHAPES = (
    ("q", 576, 576),
    ("k", 576, 192),
    ("v", 576, 192),
    ("o", 576, 576),
    ("gate", 576, 1536),
    ("up", 576, 1536),
    ("down", 1536, 576),
)
HEAD = ("head", 576, 49152)
BATCHES = (2, 3)


def make_run(k, n, weights):
    def one(batch, payload):
        mod = RKNNMatmul(SDK, k, n, weights, batch=batch, system_runtime=True)
        try:
            raw, timing = mod.run(payload)
            return mod, raw, timing
        except BaseException:
            try:
                mod.close()
            except BaseException:
                pass
            raise
    return one


def check_weight(path, k, n):
    size = path.stat().st_size
    if size != k * n:
        raise ValueError(f"{path.name}: expected {k*n} bytes, got {size}")


def main():
    items = []
    for layer in range(LAYERS):
        for label, k, n in LAYER_SHAPES:
            items.append((f"l{layer:02d}_{label}", k, n, FIX / f"l{layer:02d}_{label}.i8.bin"))
    items.append((HEAD[0], HEAD[1], HEAD[2], FIX / "head.i8.bin"))

    summary = {"schema": "NPU_LINEAR_BATCH_V1", "layers": LAYERS, "items": len(items),
               "batches": list(BATCHES), "groups": [], "status": "running"}
    totals = {b: {"step_us": 0.0, "exact": 0, "count": 0} for b in (1, 2, 3)}
    group = {}
    try:
        for name, k, n, path in items:
            check_weight(path, k, n)
            weights = path.read_bytes()
            A = os.urandom(3 * k)
            run = make_run(k, n, weights)
            singles = []
            for row in range(3):
                mod, raw, timing = run(1, A[row * k:(row + 1) * k])
                singles.append(raw)
                totals[1]["step_us"] += timing["step_us"]
                totals[1]["count"] += 1
                mod.close()
            tag = name.split("_", 1)[1] if name.startswith("l") else name
            for batch in BATCHES:
                mod, raw, timing = run(batch, A[:batch * k])
                try:
                    rows = [raw[b * n * 4:(b + 1) * n * 4] for b in range(batch)]
                    exact = all(rows[b] == singles[b] for b in range(batch))
                    totals[batch]["step_us"] += timing["step_us"]
                    totals[batch]["count"] += 1
                    if exact:
                        totals[batch]["exact"] += 1
                    g = group.setdefault((tag, k, n), {
                        "count": 0,
                        "batch_2_exact": 0, "batch_2_step_us": 0.0,
                        "batch_3_exact": 0, "batch_3_step_us": 0.0,
                    })
                    g["count"] += 1
                    g[f"batch_{batch}_exact"] += 1 if exact else 0
                    g[f"batch_{batch}_step_us"] += timing["step_us"]
                    if not exact:
                        summary.setdefault("mismatches", []).append(
                            {"name": name, "shape": [k, n], "batch": batch})
                finally:
                    mod.close()
        for (tag, k, n), g in group.items():
            summary["groups"].append({"tag": tag, "shape": [k, n], **g})
        summary["totals"] = totals
        summary["status"] = "PASS" if all(
            totals[b]["exact"] == totals[b]["count"] for b in BATCHES) else "BATCH_MISMATCH"
    except BaseException as exc:
        summary.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
    out = Path("/home/kvdev/work_pc2_pcie/batch_probe_20261030/npu_linear_batch_summary.json")
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary.get(k) for k in ("status", "items", "totals", "error")}, indent=2), flush=True)
    print("SUMMARY=" + str(out), flush=True)


if __name__ == "__main__":
    main()
