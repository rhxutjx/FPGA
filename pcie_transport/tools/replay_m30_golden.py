#!/usr/bin/env python3
"""Replay B/PC1's 30-layer x 84-position M golden through the functional M bit."""
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
    manifest = json.loads((a.golden / "real_npu_frame_manifest.json").read_text(encoding="utf-8"))
    frames = manifest["frames"]
    inp = (a.golden / "real_npu_qkv.fp16.bin").read_bytes()
    exp = (a.golden / "real_npu_expected_m.fp16.bin").read_bytes()
    if len(frames) != 2520:
        raise SystemExit("not 2520 frames")
    device = BoardDevice()
    status = BoardStatus()
    controller = PlanBStatusController(lambda: status.read(0xA4),
                                       lambda value: status.write(0xA8, value))
    transport = V3Transport(device, controller, timeout_s=a.timeout, start_seq=1)
    records = []
    try:
        transport.reset_all()
        for row in frames:
            layer, position = row["layer"], row["position"]
            if not (0 <= layer < 30 and 0 <= position < 84):
                raise RuntimeError("bad frame index")
            raw = inp[row["input_offset"]:row["input_offset"] + 1920]
            expected = exp[row["expected_offset"]:row["expected_offset"] + 1152]
            if len(raw) != 1920 or len(expected) != 1152:
                raise RuntimeError("bad slice")
            result = transport.attention(0, layer, position, raw)
            if result.payload != expected:
                raise RuntimeError(f"payload mismatch p{position} l{layer}")
            records.append({"layer": layer, "position": position, "seq": result.seq})
        summary = {
            "schema": "M_30_LAYER_84_POS_REPLAY_V1",
            "result": "M30_GOLDEN_OK",
            "frames": len(records),
            "first": records[0],
            "last": records[-1],
            "input_sha256": hashlib.sha256(inp).hexdigest(),
            "expected_sha256": hashlib.sha256(exp).hexdigest(),
            "note": "B/PC1 independent M golden; fixed 30-layer trajectory; not three-prompt batch/closed-loop",
        }
        print(json.dumps({k: summary[k] for k in ("result", "frames", "first", "last")}, indent=2))
        a.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    finally:
        device.close()
        status.close()


if __name__ == "__main__":
    main()
