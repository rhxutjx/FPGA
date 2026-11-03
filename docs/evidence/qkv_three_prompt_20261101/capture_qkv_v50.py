#!/usr/bin/env python3
"""Capture two independent prompt QKV with RK NPU linear + CPU reference attention.

This is an INTERIM handoff for B: Q/K/V are actual RK NPU post-RoPE values,
but the attention/feedback path is CPU F32 reference, NOT the M FPGA. It must
not be labelled as M closed-loop input or M golden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class NullJournal:
    def run(self, name, fn, **kwargs):
        return fn()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v50-root", type=Path, required=True)
    parser.add_argument("--assets-host", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompts", default="1,2")
    parser.add_argument("--max-new-tokens", type=int, default=1)
    args = parser.parse_args(argv)

    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("refuse to overwrite output")
    args.output.mkdir(parents=True)

    v50 = str(args.v50_root)
    if v50 not in sys.path:
        sys.path.insert(0, v50)

    from host.backends.rknn_linear_engine import RKNNLinearEngine
    from host.backends.rknn_session import VerifiedRKNNEnvironment
    from host.model.inference_runtime import CPUReferenceWithVectors, InferenceRuntime, RuntimeAssets
    from host.model.tokenizer_adapter import HFTokenizer
    from host.tools.m_live_demo_v50 import (BOSTokenizer, PROMPTS, TOKENIZER_SHA256,
                                            token_ids_for_demo)
    from pcie_contract import contract as wire

    prompt_indices = [int(x) - 1 for x in args.prompts.split(",") if x.strip()]
    if not prompt_indices or any(i not in (0, 1, 2) for i in prompt_indices):
        raise SystemExit("prompts must be a nonempty subset of 1,2,3")
    if args.max_new_tokens < 1:
        raise SystemExit("max-new-tokens must be >=1")

    sys.path.insert(0, str(args.assets_host / ".vendor/tokenizers"))
    tokenizer_dir = args.assets_host / ".fixtures/text_v38/model"
    if _digest((tokenizer_dir / "tokenizer.json").read_bytes()) != TOKENIZER_SHA256:
        raise ValueError("wrong tokenizer")
    tokenizer = HFTokenizer(tokenizer_dir)
    assets = RuntimeAssets.load(args.assets_host)
    environment = VerifiedRKNNEnvironment(args.assets_host / ".vendor/rknn")
    records = []
    qkv_dir = args.output / "qkv"
    qkv_dir.mkdir()

    def factory(k, n, weights):
        return RKNNLinearEngine(environment.sdk, k, n, weights, verification=environment)

    prompt_entries = []
    for index in prompt_indices:
        label, prompt, expected_ids_sha = PROMPTS[index]
        ids = token_ids_for_demo(tokenizer, index)
        # token_ids_for_demo already validates 35 IDs + hash.
        prompt_entries.append({"prompt_index": index + 1, "label": label,
                               "prompt": prompt, "token_ids": ids,
                               "token_ids_sha256": expected_ids_sha})

    # Capture only the prompt positions (0..34); generated position 35 is ignored.
    def capture(layer, position, q, k, v, cpu_output, wire_output):
        if position >= 35:
            return
        if not (0 <= layer < 30) or len(q.values) != 576 or len(k.values) != 192 or len(v.values) != 192:
            raise ValueError("bad capture shape")
        if any(not math.isfinite(x) for x in (*q.values, *k.values, *v.values)):
            raise ValueError("non-finite QKV")
        payload = wire.pack_f16((*q.values, *k.values, *v.values))
        request_index = current_request[0]
        name = f"qkv/r{request_index}_p{position:03d}_l{layer:02d}.fp16.bin"
        path = args.output / name
        path.write_bytes(payload)
        records.append({
            "request": request_index, "prompt_index": prompt_entries[request_index]["prompt_index"],
            "position": position, "layer": layer,
            "token_id": prompt_entries[request_index]["token_ids"][position],
            "file": name, "bytes": len(payload), "sha256": _digest(payload),
        })

    attention = CPUReferenceWithVectors(assets.config, framed=None, capture=capture)
    runtime = InferenceRuntime(assets, factory, attention,
                               attention_role="CPU_REFERENCE_ONLY",
                               journal=NullJournal(), max_forwards=200,
                               max_requests=len(prompt_entries))
    current_request = [0]
    try:
        for req, entry in enumerate(prompt_entries):
            current_request[0] = req
            runtime.generate(entry["prompt"], BOSTokenizer(tokenizer),
                             max_new_tokens=args.max_new_tokens)
        summary = {
            "schema": "TWO_PROMPT_QKV_RKNPU_CPU_ATTENTION_V1",
            "status": "CAPTURED_INTERIM_NOT_M",
            "model": "SmolLM-135M board v38 assets",
            "linear_backend": "RKNN INT8 MatMul, M=1",
            "attention_backend": "CPU F32 reference (host.reference.cpu_reference.CPUAttention)",
            "fpga_used": False,
            "m_bit_used": False,
            "real_npu_linear": True,
            "real_fpga_attention": False,
            "prompt_positions": 35,
            "layers_per_position": 30,
            "records": len(records),
            "qkv_bytes": 1920,
            "qkv_layout": "Q[9,64] post-RoPE; K[3,64] post-RoPE; V[3,64] unrotated; head-major; FP16 LE",
            "order": "position-major, layer-minor; RESET per prompt; prompt order 0..34",
            "tokenizer_sha256": TOKENIZER_SHA256,
            "prompts": prompt_entries,
            "limitations": "Attention feedback is CPU reference, not M FPGA; QKV is actual RK NPU post-RoPE but deeper-layer QKV is not an M closed-loop input. Do not use as M golden or tail evidence.",
            "records_list": records,
        }
        summary["summary_sha256"] = _digest(json.dumps(summary, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        (args.output / "manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
        print(json.dumps({k: summary[k] for k in ("status", "records", "prompt_positions", "fpga_used")}, indent=2))
        return 0
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())

