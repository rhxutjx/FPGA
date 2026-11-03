#!/usr/bin/env python3
"""3 single sessions x 30 greedy rounds on functional M bit (M=1, no batch3)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101/v50")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101/v50/.vendor/tokenizers")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/v3_smoke_20261031")

from host.backends.rknn_linear_engine import RKNNLinearEngine
from host.backends.rknn_session import VerifiedRKNNEnvironment
from host.model.inference_runtime import InferenceRuntime, RuntimeAssets
from host.model.tokenizer_adapter import HFTokenizer
from host.tools.m_live_demo_v50 import BOSTokenizer, PROMPTS, token_ids_for_demo

from m3_attention_runtime import (ASSETS, BoardDevice, BoardStatus,
                                  M3Attention, NullJournal)
from v3_transport import PlanBStatusController, V3Transport


class NullJournal:
    def run(self, name, fn, **kwargs):
        return fn()


def main():
    out = Path("/home/kvdev/work_pc2_pcie/qkv_export_20261101/m3_3x30_20261103.json")
    if out.exists():
        raise SystemExit("refuse overwrite")
    assets = RuntimeAssets.load(Path(ASSETS))
    tokenizer = HFTokenizer(Path(ASSETS) / ".fixtures/text_v38/model")
    env = VerifiedRKNNEnvironment(Path(ASSETS) / ".vendor/rknn")
    device = BoardDevice()
    status = BoardStatus()
    controller = PlanBStatusController(lambda: status.read(0xA4),
                                       lambda value: status.write(0xA8, value))
    transport = V3Transport(device, controller, timeout_s=5.0, start_seq=1)
    attention = M3Attention(transport, assets.config, session=0)
    runtime = InferenceRuntime(
        assets,
        lambda k, n, w: RKNNLinearEngine(env.sdk, k, n, w, verification=env),
        attention,
        attention_role="EXPLICIT_FPGA_BACKEND",
        journal=NullJournal(),
        max_forwards=5000,
        max_requests=90,
    )
    rows = []
    start = time.perf_counter()
    try:
        for prompt_index in (1, 2, 3):
            label, prompt, ids_sha = PROMPTS[prompt_index - 1]
            ids = token_ids_for_demo(tokenizer, prompt_index - 1)
            for round_index in range(30):
                t0 = time.perf_counter()
                result, text = runtime.generate(prompt, BOSTokenizer(tokenizer),
                                                max_new_tokens=8)
                wall = time.perf_counter() - t0
                row = {
                    "prompt_index": prompt_index,
                    "label": label,
                    "round": round_index + 1,
                    "prompt_ids_sha256": ids_sha,
                    "generated_ids": list(result.generated_ids),
                    "generated_text": text,
                    "stop_reason": result.stop_reason,
                    "attention_calls": attention.calls,
                    "wall_s": wall,
                }
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                with out.open("w", encoding="utf-8") as f:
                    json.dump({
                        "schema": "M_3SINGLE_30ROUNDS_V1",
                        "status": "RUNNING",
                        "mode": "M single-session sequential; NOT batch3",
                        "prompts": len(rows),
                        "records": rows,
                        "elapsed_s": time.perf_counter() - start,
                    }, f, indent=2)
        summary = {
            "schema": "M_3SINGLE_30ROUNDS_V1",
            "status": "PASS_M_3SINGLE_30ROUNDS",
            "mode": "M single-session sequential; NOT batch3",
            "rounds_per_prompt": 30,
            "records": rows,
            "elapsed_s": time.perf_counter() - start,
            "note": "actual M FPGA Attention; no independent full-model M golden",
        }
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": summary["status"], "records": len(rows),
                          "elapsed_s": summary["elapsed_s"]}, indent=2))
    finally:
        try:
            runtime.close()
        finally:
            status.close()


if __name__ == "__main__":
    main()
