#!/usr/bin/env python3
"""Run v50 SmolLM one-token forward with v3 functional M Attention.

This is a full 30-layer host/NPU run against the M FPGA Attention path.
No independent full-model M golden is available; this records the actual run.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import select
import signal
import struct
import sys
import time
from pathlib import Path

V50 = "/home/kvdev/work_pc2_pcie/qkv_export_20261101/v50"
QKV = "/home/kvdev/work_pc2_pcie/qkv_export_20261101"
ASSETS = "/home/kvdev/work_pc1_npu/text-v38.oySckQ/host"
sys.path.insert(0, V50)
sys.path.insert(0, QKV)
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/v3_smoke_20261031")
sys.path.insert(0, str(Path(ASSETS) / ".vendor/tokenizers"))

from host.backends.rknn_linear_engine import RKNNLinearEngine
from host.backends.rknn_session import VerifiedRKNNEnvironment
from host.model.inference_runtime import InferenceRuntime, RuntimeAssets
from host.model.tokenizer_adapter import HFTokenizer
from host.tensor import Tensor
from host.tools.m_live_demo_v50 import BOSTokenizer, PROMPTS, token_ids_for_demo

from plan_b_status_v3 import decode_status, encode_status
from v3_transport import PlanBStatusController, V3Transport


H2C = "/dev/ANLOGIC-PCI0_h2c_0"
C2H = "/dev/ANLOGIC-PCI0_c2h_0"
CTRL = "/dev/ANLOGIC-PCI0_control"
IOCR = (2 << 30) | (16 << 16) | (ord("x") << 8) | 5
IOCW = (1 << 30) | (16 << 16) | (ord("x") << 8) | 4


class Deadline(Exception):
    pass


class BoardDevice:
    def __init__(self):
        self.h2c = os.open(H2C, os.O_WRONLY)
        self.c2h = os.open(C2H, os.O_RDONLY | os.O_NONBLOCK)

    def write(self, frame, *, deadline):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("deadline")
        old = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Deadline()))
        signal.setitimer(signal.ITIMER_REAL, left)
        try:
            return os.write(self.h2c, frame)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)

    def read_exact(self, count, *, deadline):
        out = bytearray()
        while len(out) < count:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("deadline")
            r, _, _ = select.select([self.c2h], [], [], left)
            if not r:
                raise TimeoutError("C2H timeout")
            chunk = os.read(self.c2h, count - len(out))
            if chunk:
                out += chunk
        return bytes(out)

    def flush_queues(self):
        while True:
            try:
                if not os.read(self.c2h, 65536):
                    break
            except OSError:
                break

    def close(self):
        os.close(self.h2c)
        os.close(self.c2h)


class BoardStatus:
    def __init__(self):
        self.fd = os.open(CTRL, os.O_RDWR)

    def read(self, offset):
        req = struct.pack("<HHIII", 0, 0, offset, 0, 0)
        out = fcntl.ioctl(self.fd, IOCR, req, True)
        return struct.unpack("<HHIII", out)[4]

    def write(self, offset, value):
        req = struct.pack("<HHIII", 0, 0, offset, value, 0)
        fcntl.ioctl(self.fd, IOCW, req)

    def close(self):
        os.close(self.fd)


class M3Attention:
    def __init__(self, transport, config, session=0):
        self.transport = transport
        self.config = config
        self.session = session
        self.calls = 0
        self.layer = 0
        self.position = 0

    def reset(self):
        self.transport.reset_all()
        self.calls = 0
        self.layer = 0
        self.position = 0

    def run_attention(self, layer, position, q, k, v):
        if (layer, position) != (self.layer, self.position):
            raise RuntimeError(f"unexpected order {(layer, position)} != {(self.layer, self.position)}")
        payload = struct.pack("<960e", *q.values, *k.values, *v.values)
        result = self.transport.attention(self.session, layer, position, payload)
        if len(result.payload) != 1152:
            raise RuntimeError("bad Attention response")
        self.calls += 1
        self.layer += 1
        if self.layer == self.config.layers:
            self.layer = 0
            self.position += 1
        return Tensor.f32(struct.unpack("<576e", result.payload), layer_id=layer, position=position)

    def close(self):
        self.transport.device.close()


class NullJournal:
    def run(self, name, fn, **kwargs):
        return fn()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("refuse overwrite")

    tokenizer_dir = Path(ASSETS) / ".fixtures/text_v38/model"
    tokenizer = HFTokenizer(tokenizer_dir)
    device = BoardDevice()
    status = BoardStatus()
    controller = PlanBStatusController(lambda: status.read(0xA4),
                                       lambda value: status.write(0xA8, value))
    transport = V3Transport(device, controller, timeout_s=5.0, start_seq=1)
    assets = RuntimeAssets.load(Path(ASSETS))
    env = VerifiedRKNNEnvironment(Path(ASSETS) / ".vendor/rknn")
    attention = M3Attention(transport, assets.config, session=0)
    runtime = InferenceRuntime(
        assets,
        lambda k, n, w: RKNNLinearEngine(env.sdk, k, n, w, verification=env),
        attention,
        attention_role="EXPLICIT_FPGA_BACKEND",
        journal=NullJournal(),
        max_forwards=100,
        max_requests=1,
    )
    label, prompt, ids_sha = PROMPTS[args.prompt - 1]
    ids = token_ids_for_demo(tokenizer, args.prompt - 1)
    start = time.perf_counter()
    try:
        result, text = runtime.generate(prompt, BOSTokenizer(tokenizer),
                                        max_new_tokens=args.max_new_tokens)
        elapsed = time.perf_counter() - start
        summary = {
            "schema": "M3_FULL_30_LAYER_ONE_TOKEN_V1",
            "status": "PASS_M_FULL_FORWARD",
            "bit_family": "v3 functional BAR",
            "prompt_index": args.prompt,
            "prompt": prompt,
            "prompt_ids": ids,
            "prompt_ids_sha256": ids_sha,
            "prompt_positions": len(ids),
            "forward_positions": len(result.forward_input_ids),
            "generated_ids": list(result.generated_ids),
            "generated_text": text,
            "stop_reason": result.stop_reason,
            "attention_calls": attention.calls,
            "host_wall_s": elapsed,
            "note": "actual M FPGA Attention, no independent full-model M golden",
        }
        print(json.dumps(summary, indent=2))
        args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    finally:
        try:
            runtime.close()
        finally:
            status.close()


if __name__ == "__main__":
    main()






