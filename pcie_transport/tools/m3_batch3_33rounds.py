#!/usr/bin/env python3
"""M batch3: 3 warmup + 30 measured greedy rounds on functional M bit."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = "/home/kvdev/work_pc2_pcie/rk_batch_20261103"
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + "/v50")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101")

from host.backends.batch_rknn import RKNNBatchEngine
from host.backends.v3_batch_attention import V3BatchAttention
from host.model.batch_generation import generate_batch
from host.model.batch_runtime import BatchRuntime
from host.model.inference_runtime import RuntimeAssets

from transport_factory import factory as transport_factory

ASSETS = "/home/kvdev/work_pc1_npu/text-v38.oySckQ/host"
SDK = Path(ASSETS) / ".vendor/rknn"
PROMPTS = ROOT + "/prompts_3.json"
OUT = ROOT + "/m3_batch3_33rounds_20261103.json"


def main():
    out = Path(OUT)
    if out.exists():
        raise SystemExit("refuse overwrite")
    prompts = json.loads(Path(PROMPTS).read_text(encoding="utf-8"))
    if len(prompts) != 3:
        raise SystemExit("need 3 prompts")
    assets = RuntimeAssets.load(Path(ASSETS))
    transport = transport_factory()
    attention = V3BatchAttention(assets.config, transport)
    model = None
    rows = []
    try:
        t_init = time.perf_counter()
        model = BatchRuntime(
            assets,
            lambda k, n, w, b: RKNNBatchEngine(SDK, k, n, w, b),
            attention, batch=3)
        init_s = time.perf_counter() - t_init
        for phase, count in (("warmup", 3), ("measured", 30)):
            for index in range(1, count + 1):
                t0 = time.perf_counter()
                results = generate_batch(model, prompts, max_new_tokens=8,
                                         eos_token_ids=(0,))
                wall = time.perf_counter() - t0
                row = {
                    "phase": phase,
                    "round": index,
                    "wall_s": wall,
                    "generated_token_count": sum(len(r["generated_ids"]) for r in results),
                    "results": [{"generated_ids": list(r["generated_ids"]),
                                 "stop_reason": r["stop_reason"]} for r in results],
                }
                if phase == "measured":
                    rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                out.write_text(json.dumps({
                    "schema": "M_BATCH3_3WARMUP_30ROUNDS_V1",
                    "status": "RUNNING",
                    "init_s": init_s,
                    "warmup_rounds": 3,
                    "measured_rounds": rows,
                }, indent=2), encoding="utf-8")
        total_tokens = sum(r["generated_token_count"] for r in rows)
        total_wall = sum(r["wall_s"] for r in rows)
        summary = {
            "schema": "M_BATCH3_3WARMUP_30ROUNDS_V1",
            "status": "PASS_M_BATCH3_30ROUNDS",
            "init_s": init_s,
            "warmup_rounds": 3,
            "measured_rounds": rows,
            "total_tokens": total_tokens,
            "total_wall_s": total_wall,
            "aggregate_tokens_s": total_tokens / total_wall if total_wall > 0 else 0,
            "note": "M-only; not B/M; Attention single-inflight",
        }
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({"status": summary["status"],
                          "rounds": len(rows),
                          "total_tokens": total_tokens,
                          "total_wall_s": total_wall,
                          "aggregate_tokens_s": summary["aggregate_tokens_s"]}, indent=2))
    finally:
        if model is not None:
            model.close()
        else:
            try:
                transport.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()

