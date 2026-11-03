#!/usr/bin/env python3
"""NPU INT8 MatMul batch shape sweep (no-C-init production wrapper, batch=2/3)."""
import json
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_matmul_noc import RKNNMatmul

SDK = Path("/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.vendor/rknn")
SHAPES = (
    (576, 576, "Q/O"),
    (576, 192, "K/V"),
    (576, 1536, "gate/up"),
    (1536, 576, "down"),
    (576, 49152, "LM head"),
)


def run(batch, payload, B, k, n):
    mod = RKNNMatmul(SDK, k, n, B, batch=batch, system_runtime=True)
    try:
        raw, timing = mod.run(payload)
        return mod, raw, timing
    except BaseException:
        try:
            mod.close()
        except BaseException:
            pass
        raise


for k, n, label in SHAPES:
    B = os.urandom(k * n)
    A = os.urandom(3 * k)
    rec = {"shape": [k, n], "label": label, "status": "running"}
    try:
        singles = []
        for row in range(3):
            mod, raw, timing = run(1, A[row * k:(row + 1) * k], B, k, n)
            singles.append(raw)
            mod.close()
        rec["single_bytes"] = [len(x) for x in singles]
        for batch in (2, 3):
            mod, raw, timing = run(batch, A[:batch * k], B, k, n)
            try:
                rows = [raw[b * n * 4:(b + 1) * n * 4] for b in range(batch)]
                exact = all(rows[b] == singles[b] for b in range(batch))
                rec[f"batch_{batch}"] = {
                    "exact_vs_single": exact,
                    "step_us": round(timing["step_us"], 3),
                    "run_api_us": round(timing["run_api_us"], 3),
                    "create_us": round(mod.create_us, 3),
                    "setup_us": round(mod.setup_us, 3),
                    "attrs": {name: mod.attr_dict(getattr(mod.attrs, name)) for name in ("A", "B", "C")},
                }
            finally:
                mod.close()
        rec["status"] = ("PASS" if all(rec[f"batch_{b}"]["exact_vs_single"] for b in (2, 3))
                         else "BATCH_VS_SINGLE_MISMATCH")
    except BaseException as exc:
        rec.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
    print(json.dumps(rec, ensure_ascii=False), flush=True)
