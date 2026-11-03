#!/usr/bin/env python3
"""Replay B's 70-frame layer14 golden through the functional M bit.

Uses the PC2 smoke helpers for STATUS/CONTROL and re-encodes each expected
frame with a new host seq. This is not an M closed-loop/3-prompt golden.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

BASE = "/home/kvdev/work_pc2_pcie/v3_smoke_20261031"
sys.path.insert(0, BASE)
sys.path.insert(0, "/home/kvdev/work_pc2_pcie/qkv_export_20261101")
import multisession_v3 as codec
from run_v3_smoke_on_board import (_read_exact, _status, _write_deadline,
                                   _write_reg, _poll_ready)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--golden", type=Path, required=True)
    p.add_argument("--status-offset", type=lambda s: int(s, 0), default=0xA4)
    p.add_argument("--control-offset", type=lambda s: int(s, 0), default=0xA8)
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    manifest = json.loads((a.golden / "manifest.json").read_text(encoding="utf-8"))
    req = (a.golden / "request_frames.bin").read_bytes()
    exp = (a.golden / "expected_frames.bin").read_bytes()
    records = manifest["records"]
    if len(records) != 70:
        raise SystemExit("not 70 frames")
    ctrl = __import__("os").open("/dev/ANLOGIC-PCI0_control", __import__("os").O_RDWR)
    seq = 1
    results = []
    try:
        for row in records:
            ro, rl = row["request_offset"], row["request_length"]
            raw_req = req[ro:ro + rl]
            h, payload = codec.unpack_frame(raw_req, direction="h2c")
            # Re-encode with fresh host seq; preserve op/session/layer/position.
            frame = codec.pack_request(seq=seq, op=h.op, layer=h.layer,
                                       position=h.position, session_id=h.session_id,
                                       payload=payload)
            written = _write_deadline(frame, a.timeout)
            if written != len(frame):
                raise RuntimeError("short write")
            if h.op == codec.OP_RESET_CACHE:
                ack = _read_exact(32, a.timeout)
                ah, ap = codec.unpack_frame(ack, direction="c2h")
                if (ah.op != codec.OP_RESET_CACHE or ah.seq != seq
                        or ah.session_id != 255 or ah.layer != 255
                        or ah.position != 0 or ap):
                    raise RuntimeError("RESET ACK mismatch")
                _poll_ready(ctrl, a.status_offset, a.timeout)
                status = 0
                expected_hash = None
            else:
                raw_resp = _read_exact(1184, a.timeout)
                rh, rp = codec.unpack_frame(raw_resp, direction="c2h")
                if (rh.op != h.op or rh.seq != seq or rh.session_id != h.session_id
                        or rh.layer != h.layer or rh.position != h.position):
                    raise RuntimeError("response header mismatch")
                eo, el = row["response_offset"], row["response_length"]
                eh, ep = codec.unpack_frame(exp[eo:eo + el], direction="c2h")
                if rp != ep:
                    raise RuntimeError("expected payload mismatch at frame %d" % row["index"])
                expected_hash = hashlib.sha256(rp).hexdigest()
                _write_reg(ctrl, 0, a.control_offset, 1 << 2)  # ACK_DONE
                _, st = _poll_ready(ctrl, a.status_offset, a.timeout)
                status = int(__import__("plan_b_status_v3", fromlist=["encode_status"]).encode_status(st))
            results.append({"index": row["index"], "seq": seq, "op": h.op,
                            "session": h.session_id, "layer": h.layer,
                            "position": h.position,
                            "expected_payload_sha256": expected_hash,
                            "status": status})
            seq += 1
        summary = {"schema": "B_LAYER14_70_FRAME_REPLAY_V1", "result": "GOLDEN_70_OK",
                   "frames": len(results), "status_offset": a.status_offset,
                   "control_offset": a.control_offset, "records": results}
        print(json.dumps(summary, indent=2))
        a.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    finally:
        __import__("os").close(ctrl)


if __name__ == "__main__":
    main()
