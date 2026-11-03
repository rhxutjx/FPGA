#!/usr/bin/env python3
"""Capture per-step generated logits for 3 prompts: CPU reference or B bit."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101/v50")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101/v50/.vendor/tokenizers")
sys.path.insert(0, "/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.vendor/tokenizers")
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/v3_smoke_20261031")

from host.backends.rknn_linear_engine import RKNNLinearEngine
from host.backends.rknn_session import VerifiedRKNNEnvironment
from host.model.inference_runtime import (CPUReferenceWithVectors, InferenceRuntime,
                                          RuntimeAssets)
from host.model.tokenizer_adapter import HFTokenizer
from host.tools.m_live_demo_v50 import BOSTokenizer, PROMPTS

from m3_attention_runtime import ASSETS, BoardDevice, BoardStatus, M3Attention, NullJournal
from v3_transport import PlanBStatusController, V3Transport


def make_runtime(mode):
    assets = RuntimeAssets.load(Path(ASSETS))
    tokenizer = HFTokenizer(Path(ASSETS) / ".fixtures/text_v38/model")
    env = VerifiedRKNNEnvironment(Path(ASSETS) / ".vendor/rknn")
    if mode == "reference":
        attention = CPUReferenceWithVectors(assets.config)
        role = "CPU_REFERENCE_ONLY"
        closer = None
    else:
        device = BoardDevice()
        status = BoardStatus()
        controller = PlanBStatusController(lambda: status.read(0xA4),
                                           lambda value: status.write(0xA8, value))
        transport = V3Transport(device, controller, timeout_s=5.0, start_seq=1)
        attention = M3Attention(transport, assets.config, session=0)
        role = "EXPLICIT_FPGA_BACKEND"
        closer = status
    runtime = InferenceRuntime(
        assets,
        lambda k, n, w: RKNNLinearEngine(env.sdk, k, n, w, verification=env),
        attention,
        attention_role=role,
        journal=NullJournal(), max_forwards=300, max_requests=3,
    )
    return runtime, tokenizer, closer


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("reference", "b"), required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists() or a.out.is_dir():
        raise SystemExit("refuse overwrite")
    a.out.mkdir(parents=True)
    runtime, tokenizer, closer = make_runtime(a.mode)
    logits = []
    bin_path = a.out / "logits.f32.bin"
    stream = bin_path.open("wb")
    try:
        for index in (1, 2, 3):
            label, prompt, ids_sha = PROMPTS[index - 1]
            ids = BOSTokenizer(tokenizer).encode(prompt)
            prompt_len = len(ids)
            captured = []

            def after_forward(request, position, values):
                if not (prompt_len - 1 <= position < prompt_len - 1 + 8):
                    return
                if len(values.values) != 49152:
                    raise RuntimeError("bad logits length")
                raw = array.array("f", values.values).tobytes()
                offset = stream.tell()
                stream.write(raw)
                captured.append({
                    "position": position,
                    "offset": offset,
                    "length": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                })

            runtime.after_forward = after_forward
            result, text = runtime.generate(prompt, BOSTokenizer(tokenizer),
                                            max_new_tokens=8)
            logits.append({
                "prompt_index": index,
                "label": label,
                "prompt_ids_sha256": ids_sha,
                "generated_ids": list(result.generated_ids),
                "generated_text": text,
                "stop_reason": result.stop_reason,
                "logits": captured,
            })
            print(json.dumps({k: logits[-1][k] for k in
                              ("prompt_index", "generated_ids", "generated_text")},
                             ensure_ascii=False), flush=True)
        summary = {
            "schema": "PER_STEP_LOGITS_3PROMPTS_V1",
            "mode": a.mode,
            "source": "PC1 v50 NPU linear + CPU F32 attention" if a.mode == "reference"
                      else "current B bit; M3Attention session0",
            "logits_file": "logits.f32.bin",
            "logits_file_sha256": hashlib.sha256(bin_path.read_bytes()).hexdigest(),
            "results": logits,
        }
        (a.out / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n",
                                             encoding="utf-8")
        print(json.dumps({"mode": a.mode, "prompts": 3,
                          "logits_file_sha256": summary["logits_file_sha256"]}, indent=2))
    finally:
        stream.close()
        runtime.close()
        if closer:
            closer.close()


if __name__ == "__main__":
    main()
