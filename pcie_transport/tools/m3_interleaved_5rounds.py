#!/usr/bin/env python3
"""Five interleaved 3-session rounds on the functional M bit."""
from __future__ import annotations

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
from m3_interleaved_3sessions import LockedEngine, M3SessionAttention, WorkerDevice
from v3_transport import PlanBStatusController, V3Transport


def main():
    rounds = 5
    out = Path("/home/kvdev/work_pc2_pcie/qkv_export_20261101/m3_interleaved_5rounds_20261103.json")
    if out.exists():
        raise SystemExit("refuse overwrite")
    assets = RuntimeAssets.load(Path(ASSETS))
    tokenizer = HFTokenizer(Path(ASSETS) / ".fixtures/text_v38/model")
    env = VerifiedRKNNEnvironment(Path(ASSETS) / ".vendor/rknn")
    engine_lock = threading.RLock()
    transport_lock = threading.RLock()
    cache = {}

    def factory(k, n, w):
        import hashlib
        key = (k, n, hashlib.sha256(w).digest())
        with engine_lock:
            if key not in cache:
                cache[key] = LockedEngine(
                    RKNNLinearEngine(env.sdk, k, n, w, verification=env),
                    engine_lock)
            return cache[key]

    device = WorkerDevice()
    status = BoardStatus()
    controller = PlanBStatusController(lambda: status.read(0xA4),
                                       lambda value: status.write(0xA8, value))
    transport = V3Transport(device, controller, timeout_s=5.0, start_seq=1)
    all_rounds = []
    try:
        for round_index in range(1, rounds + 1):
            transport.reset_all()
            attentions = [M3SessionAttention(transport, assets.config, s, transport_lock)
                          for s in (0, 1, 2)]
            runtimes = [InferenceRuntime(
                assets, factory, attentions[s],
                attention_role="EXPLICIT_FPGA_BACKEND",
                journal=NullJournal(), max_forwards=50, max_requests=1)
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
            t0 = time.perf_counter()
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            wall = time.perf_counter() - t0
            row = {"round": round_index, "wall_s": wall, "results": results,
                   "errors": errors}
            all_rounds.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            out.write_text(json.dumps({"schema": "M_INTERLEAVED_5ROUNDS_V1",
                                       "status": "RUNNING", "rounds": all_rounds},
                                      indent=2), encoding="utf-8")
            for r in runtimes:
                try:
                    r.close()
                except Exception:
                    pass
        summary = {"schema": "M_INTERLEAVED_5ROUNDS_V1",
                   "status": "PASS_M_INTERLEAVED_5ROUNDS",
                   "rounds": all_rounds}
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({"status": summary["status"], "rounds": rounds}, indent=2))
    finally:
        device.close()
        status.close()


if __name__ == "__main__":
    main()
