#!/usr/bin/env python3
"""Three single-session prompts advanced concurrently on the M v3 functional bit.

Host threads interleave session 0/1/2; V3Transport serializes the single-inflight
attention frames. This is interleaved/pipelined host scheduling, NOT three
parallel FPGA Attention engines.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
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
from host.tensor import Tensor
from host.tools.m_live_demo_v50 import BOSTokenizer, PROMPTS, token_ids_for_demo

from m3_attention_runtime import ASSETS, BoardDevice, BoardStatus, NullJournal


class WorkerDevice(BoardDevice):
    def write(self, frame, *, deadline):
        return os.write(self.h2c, frame)
from v3_transport import PlanBStatusController, V3Transport


class LockedEngine:
    def __init__(self, engine, lock):
        self.engine, self.lock = engine, lock

    def metadata(self):
        return self.engine.metadata()

    def run(self, data):
        with self.lock:
            return self.engine.run(data)

    def close(self):
        return None


class M3SessionAttention:
    def __init__(self, transport, config, session, transport_lock):
        self.transport = transport
        self.config = config
        self.session = session
        self.lock = transport_lock
        self.calls = 0
        self.position = 0
        self.layer = 0

    def reset(self):
        # Global RESET is issued once before the three workers start.
        self.calls = 0
        self.position = 0
        self.layer = 0

    def run_attention(self, layer, position, q, k, v):
        if (layer, position) != (self.layer, self.position):
            raise RuntimeError(f"session {self.session}: unexpected order {(layer, position)}")
        payload = struct.pack("<960e", *q.values, *k.values, *v.values)
        with self.lock:
            result = self.transport.attention(self.session, layer, position, payload)
        if len(result.payload) != 1152:
            raise RuntimeError("bad Attention response")
        self.calls += 1
        self.layer += 1
        if self.layer == self.config.layers:
            self.layer = 0
            self.position += 1
        return __import__("host.tensor", fromlist=["Tensor"]).Tensor.f32(
            __import__("struct").unpack("<576e", result.payload),
            layer_id=layer, position=position)

    def close(self):
        return None


def main():
    out = Path("/home/kvdev/work_pc2_pcie/qkv_export_20261101/m3_interleaved_3sessions_20261103.json")
    if out.exists():
        raise SystemExit("refuse overwrite")
    assets = RuntimeAssets.load(Path(ASSETS))
    tokenizer = HFTokenizer(Path(ASSETS) / ".fixtures/text_v38/model")
    env = VerifiedRKNNEnvironment(Path(ASSETS) / ".vendor/rknn")
    engine_lock = threading.RLock()
    transport_lock = threading.RLock()
    cache = {}

    def factory(k, n, w):
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
    # One global RESET for all three sessions.
    transport.reset_all()
    attentions = [M3SessionAttention(transport, assets.config, s, transport_lock)
                  for s in (0, 1, 2)]
    runtimes = [
        InferenceRuntime(assets, factory, attentions[s],
                         attention_role="EXPLICIT_FPGA_BACKEND",
                         journal=NullJournal(), max_forwards=50,
                         max_requests=1)
        for s in (0, 1, 2)
    ]
    results = [None, None, None]
    errors = [None, None, None]
    barrier = threading.Barrier(3)

    def worker(index):
        try:
            barrier.wait()
            label, prompt, _ = PROMPTS[index]
            t0 = time.perf_counter()
            result, text = runtimes[index].generate(
                prompt, BOSTokenizer(tokenizer), max_new_tokens=8)
            results[index] = {
                "session": index,
                "label": label,
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
    try:
        if any(errors):
            summary = {"schema": "M_INTERLEAVED_3SESSION_V1",
                       "status": "FAIL", "errors": errors, "wall_s": wall,
                       "results": results}
        else:
            total_tokens = sum(len(r["generated_ids"]) for r in results)
            summary = {
                "schema": "M_INTERLEAVED_3SESSION_V1",
                "status": "PASS_M_INTERLEAVED_3SESSION",
                "mode": "host interleaved/pipelined; endpoint single-inflight; NOT parallel Attention/batch3",
                "wall_s": wall,
                "total_output_tokens": total_tokens,
                "aggregate_tokens_s": total_tokens / wall if wall > 0 else 0,
                "results": results,
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





