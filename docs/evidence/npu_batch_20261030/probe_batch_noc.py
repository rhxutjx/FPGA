#!/usr/bin/env python3
"""NPU INT8 MatMul batch capability probe.

Primary check: for each row, NPU batch=M output must equal the NPU single-row
output for the same A row and B weights. CPU int8 dot is also reported, but the
production wrapper's layout/quantization semantics are separate from batch.
No model, no FPGA, no H2C.
"""
import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_matmul_noc import RKNNMatmul

SDK = Path("/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.vendor/rknn")
K = 576
N = 576
BATCHES = (2, 3)
rng = random.Random(20261030)
# Avoid -128 initially: some INT8 kernels treat it unusually. Values are still full-range.
B_i = [rng.randrange(-127, 128) for _ in range(K * N)]
A_i = [rng.randrange(-127, 128) for _ in range(3 * K)]
B = bytes(x & 0xff for x in B_i)
A = bytes(x & 0xff for x in A_i)
expected = []
for b in range(3):
    row = []
    base = b * K
    for j in range(N):
        total = 0
        for i in range(K):
            total += A_i[base + i] * B_i[i * N + j]
        row.append(total)
    expected.append(row)


def npu_run(batch, payload):
    mod = RKNNMatmul(SDK, K, N, B, batch=batch, system_runtime=True)
    try:
        raw, timing = mod.run(payload)
        out = list(struct.unpack(f"<{batch * N}i", raw))
        return mod, out, timing
    except BaseException:
        try:
            mod.close()
        except BaseException:
            pass
        raise


def diffs(out, ref):
    mism = 0
    max_abs = 0
    for a, b in zip(out, ref):
        d = abs(a - b)
        if d:
            mism += 1
            if d > max_abs:
                max_abs = d
    return mism, max_abs


print(json.dumps({"event": "probe_start", "k": K, "n": N, "sdk": str(SDK),
                  "note": "batch-vs-single is the primary gate; CPU int8 dot is separate"}), flush=True)

single = {}
for b in range(3):
    mod = None
    try:
        mod, out, timing = npu_run(1, A[b * K:(b + 1) * K])
        single[b] = out
        cpu_m, cpu_d = diffs(out, expected[b])
        print(json.dumps({"event": "single_row", "row": b, "status": "PASS",
                          "cpu_mismatches": cpu_m, "cpu_max_abs_diff": cpu_d,
                          "step_us": round(timing["step_us"], 3),
                          "versions": mod.versions}), flush=True)
    except BaseException as exc:
        single[b] = None
        print(json.dumps({"event": "single_row", "row": b, "status": "FAILED",
                          "error_type": type(exc).__name__, "error": str(exc)}), flush=True)
    finally:
        if mod is not None:
            try:
                mod.close()
            except BaseException as exc:
                print(json.dumps({"event": "single_close_error", "row": b, "error": str(exc)}), flush=True)

for batch in BATCHES:
    rec = {"event": "batch", "batch": batch, "status": "FAILED"}
    mod = None
    try:
        mod, out, timing = npu_run(batch, A[: batch * K])
        row_mismatches = []
        row_max = []
        for b in range(batch):
            row_out = out[b * N:(b + 1) * N]
            if single[b] is None:
                row_mismatches.append(None)
                row_max.append(None)
            else:
                m, d = diffs(row_out, single[b])
                row_mismatches.append(m)
                row_max.append(d)
        cpu_m, cpu_d = diffs(out, [expected[b][j] for b in range(batch) for j in range(N)])
        effective = all(x == 0 for x in row_mismatches)
        rec.update(
            status="PASS" if effective else "BATCH_VS_SINGLE_MISMATCH",
            batch_vs_single_exact=effective,
            row_mismatches=row_mismatches,
            row_max_abs_diff=row_max,
            cpu_mismatches=cpu_m,
            cpu_max_abs_diff=cpu_d,
            output_bytes=len(out) * 4,
            create_us=round(mod.create_us, 3),
            setup_us=round(mod.setup_us, 3),
            timing={k: round(v, 3) for k, v in timing.items()},
            versions=mod.versions,
            attrs={name: mod.attr_dict(getattr(mod.attrs, name)) for name in ("A", "B", "C")},
        )
    except BaseException as exc:
        rec.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
    finally:
        if mod is not None:
            try:
                errors = mod.close()
                if errors:
                    rec["close_errors"] = errors
            except BaseException as exc:
                rec["close_errors"] = [str(exc)]
    print(json.dumps(rec, ensure_ascii=False), flush=True)
