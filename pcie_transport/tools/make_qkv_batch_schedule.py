#!/usr/bin/env python3
"""Build a two-session batch schedule from the QKV manifest (offline only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    records = manifest["records_list"]
    by_key = {(r["request"], r["position"], r["layer"]): r for r in records}
    if len(by_key) != 2 * 35 * 30:
        raise SystemExit("unexpected QKV record set")
    groups = []
    for position in range(35):
        for layer in range(30):
            rows = []
            for request, session in ((0, 0), (1, 1)):
                r = by_key[(request, position, layer)]
                rows.append({
                    "session": session,
                    "prompt_index": manifest["prompts"][request]["prompt_index"],
                    "token_id": r["token_id"],
                    "file": r["file"],
                    "sha256": r["sha256"],
                })
            groups.append({"position": position, "layer": layer,
                           "batch_size": 2, "rows": rows})
    out = {
        "schema": "TWO_SESSION_BATCH_SCHEDULE_FROM_QKV_V1",
        "status": "OFFLINE_SCHEDULE_ONLY_NOT_M",
        "source_qkv_status": manifest["status"],
        "batch_size": 2,
        "sessions_used": [0, 1],
        "sessions_unused": [2],
        "prompts": manifest["prompts"],
        "positions": 35,
        "layers": 30,
        "groups": groups,
        "group_count": len(groups),
        "frame_count": sum(len(g["rows"]) for g in groups),
        "order": "position-major, layer-minor; rows share (position,layer); each session preserves layer0..29 per position",
        "endpoint": "v3 endpoint is single-inflight; rows are sent serially; batch refers to host/NPU row grouping, not parallel FPGA Attention",
        "limitations": "QKV is RK NPU post-RoPE with CPU reference attention feedback; not M input/golden/tail evidence.",
    }
    if out["group_count"] != 1050 or out["frame_count"] != 2100:
        raise SystemExit("wrong schedule counts")
    path = root / "batch_schedule_2sessions_35x30.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": out["status"], "groups": out["group_count"],
                      "frames": out["frame_count"], "path": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
