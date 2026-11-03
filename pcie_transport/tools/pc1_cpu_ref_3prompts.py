#!/usr/bin/env python3
"""PC1 v50 CPU-attention full-model reference for the three prompts."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101/v50")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101/v50/.vendor/tokenizers")
sys.path.insert(0, "/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.vendor/tokenizers")

from host.backends.rknn_linear_engine import RKNNLinearEngine
from host.backends.rknn_session import VerifiedRKNNEnvironment
from host.model.inference_runtime import CPUReferenceWithVectors, InferenceRuntime, RuntimeAssets
from host.model.tokenizer_adapter import HFTokenizer
from host.tools.m_live_demo_v50 import BOSTokenizer, PROMPTS

ASSETS = "/home/kvdev/work_pc1_npu/text-v38.oySckQ/host"
OUT = "/home/kvdev/work_pc2_pcie/qkv_export_20261101/pc1_cpu_ref_3prompts_20261103.json"


class NullJournal:
    def run(self, name, fn, **kwargs):
        return fn()


def main():
    out = Path(OUT)
    if out.exists():
        raise SystemExit("refuse overwrite")
    assets = RuntimeAssets.load(Path(ASSETS))
    tokenizer = HFTokenizer(Path(ASSETS) / ".fixtures/text_v38/model")
    env = VerifiedRKNNEnvironment(Path(ASSETS) / ".vendor/rknn")
    attention = CPUReferenceWithVectors(assets.config)
    runtime = InferenceRuntime(
        assets,
        lambda k, n, w: RKNNLinearEngine(env.sdk, k, n, w, verification=env),
        attention,
        attention_role="CPU_REFERENCE_ONLY",
        journal=NullJournal(), max_forwards=300, max_requests=3,
    )
    rows = []
    try:
        start = time.perf_counter()
        for index in (1, 2, 3):
            label, prompt, ids_sha = PROMPTS[index - 1]
            t0 = time.perf_counter()
            result, text = runtime.generate(prompt, BOSTokenizer(tokenizer),
                                            max_new_tokens=8)
            rows.append({
                "prompt_index": index,
                "label": label,
                "prompt_ids_sha256": ids_sha,
                "generated_ids": list(result.generated_ids),
                "generated_text": text,
                "stop_reason": result.stop_reason,
                "wall_s": time.perf_counter() - t0,
            })
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        summary = {"schema": "PC1_CPU_REFERENCE_3PROMPTS_V1",
                   "status": "PASS_PC1_CPU_REFERENCE",
                   "source": "PC1 v50 NPU linear + CPU F32 attention; no B/M bit",
                   "results": rows,
                   "wall_s": time.perf_counter() - start}
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({"status": summary["status"], "results": len(rows),
                          "wall_s": summary["wall_s"]}, indent=2))
    finally:
        runtime.close()


if __name__ == "__main__":
    main()


