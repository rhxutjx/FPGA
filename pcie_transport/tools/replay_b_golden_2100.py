#!/usr/bin/env python3
"""Replay B's independent Spot/Mia fixed-input golden through current B bit."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

QKV = "/home/kvdev/work_pc2_pcie/qkv_export_20261101"
sys.path.insert(0, QKV)
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/v3_smoke_20261031")

from v3_transport import PlanBStatusController, V3Transport
from m3_attention_runtime import BoardDevice, BoardStatus


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--golden", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=5.0)
    a = p.parse_args()
    manifest = json.loads((a.golden / "manifest.json").read_text(encoding="utf-8"))
    frames = manifest["frames"]
    inp = (a.golden / "real_npu_qkv.fp16.bin").read_bytes()
    exp = (a.golden / "independent_b_expected.fp16.bin").read_bytes()
    if len(frames) != 2100:
        raise SystemExit("not 2100 frames")
    device = BoardDevice()
    status = BoardStatus()
    controller = PlanBStatusController(lambda: status.read(0xA4),
                                       lambda value: status.write(0xA8, value))
    transport = V3Transport(device, controller, timeout_s=a.timeout, start_seq=1)
    records = []
    try:
        current_request = None
        for row in frames:
            req = row["request"]
            if req != current_request:
                transport.reset_all()
                current_request = req
            raw = inp[row["input_offset"]:row["input_offset"] + 1920]
            expected = exp[row["expected_offset"]:row["expected_offset"] + 1152]
            if len(raw) != 1920 or len(expected) != 1152:
                raise RuntimeError("bad slices")
            result = transport.attention(0, row["layer"], row["position"], raw)
            if result.payload != expected:
                raise RuntimeError(f"payload mismatch req={req} p={row['position']} l={row['layer']}")
            records.append({"request": req, "layer": row["layer"],
                            "position": row["position"], "seq": result.seq})
        summary = {
            "schema": "B_FIXED_INPUT_GOLDEN_REPLAY_V1",
            "result": "B_GOLDEN_2100_OK",
            "frames": len(records),
            "requests": sorted({r["request"] for r in records}),
            "first": records[0],
            "last": records[-1],
            "input_sha256": hashlib.sha256(inp).hexdigest(),
            "expected_sha256": hashlib.sha256(exp).hexdigest(),
        }
        print(json.dumps({k: summary[k] for k in ("result", "frames", "requests", "first", "last")}, indent=2))
        a.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    finally:
        device.close()
        status.close()


if __name__ == "__main__":
    main()
