#!/usr/bin/env python3
"""Host optimization: 3 sessions, per-session NPU contexts, transport serial."""
from __future__ import annotations

import hashlib
import json
import sys
import threading
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

from m3_attention_runtime import ASSETS, BoardStatus, NullJournal
from m3_interleaved_3sessions import M3SessionAttention, WorkerDevice
from v3_transport import PlanBStatusController, V3Transport


def main():
    out = Path("/home/kvdev/work_pc2_pcie/qkv_export_20261101/m3_perengine_1round_20261103.json")
    if out.exists():
        raise SystemExit("refuse overwrite")
    assets = RuntimeAssets.load(Path(ASSETS))
    tokenizer = HFTokenizer(Path(ASSETS) / ".fixtures/text_v38/model")
    env = VerifiedRKNNEnvironment(Path(ASSETS) / ".vendor/rknn")
    transport_lock = threading.RLock()

    def make_factory():
        cache = {}

        def factory(k, n, w):
            key = (k, n, hashlib.sha256(w).digest())
            if key not in cache:
                cache[key] = RKNNLinearEngine(env.sdk, k, n, w, verification=env)
            return cache[key]

        return factory

    device = WorkerDevice()
    status = BoardStatus()
    controller = PlanBStatusController(lambda: status.read(0xA4),
                                       lambda value: status.write(0xA8, value))
    transport = V3Transport(device, controller, timeout_s=5.0, start_seq=1)
    transport.reset_all()
    attentions = [M3SessionAttention(transport, assets.config, s, transport_lock)
                  for s in (0, 1, 2)]
    runtimes = [InferenceRuntime(assets, make_factory(), attentions[s],
                                 attention_role="EXPLICIT_FPGA_BACKEND",
                                 journal=NullJournal(), max_forwards=50,
                                 max_requests=1)
                for s in (0, 1, 2)]
    results = [None, None, None]
    errors = [None, None, None]
    barrier = threading.Barrier(3)

    def worker(index):
        try:
            barrier.wait()
            _, prompt, _ = PROMPTS[index]
            t0 = time.perf_counter()
            result, text = runtimes[index].generate(
                prompt, BOSTokenizer(tokenizer), max_new_tokens=8)
            results[index] = {
                "session": index,
                "wall_s": time.perf_counter() - t0,
                "generated_ids": list(result.generated_ids),
                "generated_text": text,
                "stop_reason": result.stop_reason,
                "attention_calls": attentions[index].calls,
            }
        except BaseException as exc:
            errors[index] = f"{type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - start
    try:
        summary = {
            "schema": "M_PERENGINE_3SESSION_V1",
            "status": "FAIL" if any(errors) else "PASS_M_PERENGINE_3SESSION",
            "wall_s": wall,
            "total_output_tokens": sum(len(r["generated_ids"]) for r in results) if not any(errors) else 0,
            "aggregate_tokens_s": (sum(len(r["generated_ids"]) for r in results) / wall) if not any(errors) else 0,
            "results": results, "errors": errors,
        }
        print(json.dumps(summary, indent=2))
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    finally:
        for r in runtimes:
            try:
                r.close()
            except Exception:
                pass
        device.close()
        status.close()


if __name__ == "__main__":
    main()
