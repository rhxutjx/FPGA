#!/usr/bin/env python3
"""Offline replay of the 3-session QKV batch schedule through V3Transport.

This validates host-side ordering, session routing and codec/transport state
with a mock endpoint. It does NOT execute FPGA Attention or produce M golden.
"""
from __future__ import annotations

import argparse
import json
import tarfile
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pcie_contract"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import multisession_v3 as codec
import plan_b_status_v3 as pb
from pcie_transport.v3_transport import BatchItem, SessionBatchScheduler, V3Transport


class MockStatus:
    def __init__(self):
        self.ready, self.done, self.fault, self.err = 1, 0, 0, 0

    def _s(self):
        return pb.Status(ready=self.ready, done=self.done, fault=self.fault,
                         err=self.err, last_session=255)

    def poll_ready(self, deadline):
        if self.fault:
            raise RuntimeError("fault")
        if not self.ready:
            raise RuntimeError("not ready")
        return self._s()

    def poll_done(self, deadline):
        if self.fault:
            raise RuntimeError("fault")
        if not self.done:
            raise RuntimeError("not done")
        return self._s()

    def ack_done(self):
        self.done, self.ready = 0, 1

    def soft_reset(self):
        self.ready, self.done, self.fault = 1, 0, 0


class MockDevice:
    def __init__(self):
        self.status = MockStatus()
        self.responses = []
        self.frames = 0

    def write(self, frame, *, deadline):
        h, payload = codec.unpack_frame(frame, direction="h2c")
        self.frames += 1
        if h.op == codec.OP_RESET_CACHE:
            payload_out = b""
            self.status.ready, self.status.done = 1, 0
        else:
            payload_out = bytes(1152)
            self.status.ready, self.status.done = 0, 1
        self.responses.append(codec.pack_response(seq=h.seq, op=h.op, layer=h.layer,
                                                  position=h.position,
                                                  session_id=h.session_id,
                                                  payload=payload_out))
        return len(frame)

    def read_exact(self, count, *, deadline):
        raw = self.responses.pop(0)
        if len(raw) != count:
            raise RuntimeError("wrong response length")
        return raw

    def flush_queues(self):
        self.responses.clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tar", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    schedule = json.loads(args.schedule.read_text(encoding="utf-8"))
    expected_groups = schedule["group_count"]
    expected_frames = schedule["frame_count"]
    with tempfile.TemporaryDirectory(prefix="qkv_replay_") as tmp:
        with tarfile.open(args.tar, "r:gz") as archive:
            archive.extractall(tmp)
        root = Path(tmp)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest["records"] != expected_frames:
            raise SystemExit("manifest/schedule count mismatch")
        device = MockDevice()
        status = device.status
        transport = V3Transport(device, status, timeout_s=5.0)
        transport.reset_all()
        scheduler = SessionBatchScheduler(transport, max_batch=3)
        seen = 0
        for group in schedule["groups"]:
            items = []
            for row in group["rows"]:
                payload = (root / row["file"]).read_bytes()
                if len(payload) != 1920:
                    raise SystemExit("bad payload")
                items.append(BatchItem(session=row["session"], layer=group["layer"],
                                       position=group["position"], payload=payload))
            results = scheduler.attention_batch(items)
            if [r.session for r in results] != [0, 1, 2]:
                raise SystemExit("session order mismatch")
            seen += len(results)
        summary = {
            "schema": "QKV_BATCH_MOCK_REPLAY_V1",
            "status": "MOCK_REPLAY_OK",
            "groups": expected_groups,
            "frames": seen,
            "device_frames": device.frames,
            "last_seq": transport.next_seq - 1,
            "sessions": [0, 1, 2],
            "source": "QKV RK-NPU + CPU attention feedback; mock endpoint, no FPGA",
            "not_m_golden": True,
        }
        if seen != expected_frames:
            raise SystemExit("frame count mismatch")
        print(json.dumps(summary, indent=2))
        if args.out:
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

