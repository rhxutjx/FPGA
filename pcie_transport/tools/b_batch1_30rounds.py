#!/usr/bin/env python3
"""B-mode baseline: 30 rounds of three prompts, sequential (batch=1)."""
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
from host.tools.m_live_demo_v50 import BOSTokenizer, PROMPTS

from m3_attention_runtime import (ASSETS, BoardDevice, BoardStatus, M3Attention,
                                  NullJournal)
from v3_transport import PlanBStatusController, V3Transport


def main():
    out = Path("/home/kvdev/work_pc2_pcie/qkv_export_20261101/b_batch1_30rounds_20261103.json")
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
        journal=NullJournal(), max_forwards=5000, max_requests=90,
    )
    rounds = []
    total_start = time.perf_counter()
    try:
        for round_index in range(1, 31):
            round_start = time.perf_counter()
            per_prompt = []
            for prompt_index in (1, 2, 3):
                label, prompt, ids_sha = PROMPTS[prompt_index - 1]
                t0 = time.perf_counter()
                result, text = runtime.generate(prompt, BOSTokenizer(tokenizer),
                                                max_new_tokens=8)
                per_prompt.append({
                    "prompt_index": prompt_index,
                    "label": label,
                    "prompt_ids_sha256": ids_sha,
                    "generated_ids": list(result.generated_ids),
                    "generated_text": text,
                    "stop_reason": result.stop_reason,
                    "attention_calls": attention.calls,
                    "wall_s": time.perf_counter() - t0,
                })
            row = {"round": round_index, "wall_s": time.perf_counter() - round_start,
                   "tokens": sum(len(x["generated_ids"]) for x in per_prompt),
                   "prompts": per_prompt}
            rounds.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            out.write_text(json.dumps({
                "schema": "B_BATCH1_30ROUNDS_V1",
                "status": "RUNNING",
                "rounds": rounds,
            }, indent=2), encoding="utf-8")
        total_wall = time.perf_counter() - total_start
        total_tokens = sum(r["tokens"] for r in rounds)
        summary = {
            "schema": "B_BATCH1_30ROUNDS_V1",
            "status": "PASS_B_BATCH1_30ROUNDS",
            "mode": "B batch=1; three prompts sequential each round",
            "rounds": rounds,
            "total_tokens": total_tokens,
            "total_wall_s": total_wall,
            "aggregate_tokens_s": total_tokens / total_wall,
        }
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({"status": summary["status"],
                          "rounds": len(rounds),
                          "total_tokens": total_tokens,
                          "total_wall_s": total_wall,
                          "aggregate_tokens_s": summary["aggregate_tokens_s"]}, indent=2))
    finally:
        try:
            runtime.close()
        finally:
            status.close()


if __name__ == "__main__":
    main()
