#!/usr/bin/env python3
"""Validate the two-prompt QKV manifest produced on the board."""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
records = manifest["records_list"]
if manifest["records"] != 2100 or len(records) != 2100:
    raise SystemExit("wrong record count")
if len(manifest["prompts"]) != 2:
    raise SystemExit("wrong prompt count")
if [len(p["token_ids"]) for p in manifest["prompts"]] != [35, 35]:
    raise SystemExit("wrong token count")
seen = set()
for r in records:
    key = (r["request"], r["position"], r["layer"])
    if key in seen:
        raise SystemExit("duplicate " + repr(key))
    seen.add(key)
    if not (r["request"] in (0, 1) and 0 <= r["position"] < 35 and 0 <= r["layer"] < 30):
        raise SystemExit("bad key " + repr(key))
    if r["token_id"] != manifest["prompts"][r["request"]]["token_ids"][r["position"]]:
        raise SystemExit("token mismatch " + repr(key))
    path = root / r["file"]
    raw = path.read_bytes()
    if len(raw) != 1920 or hashlib.sha256(raw).hexdigest() != r["sha256"]:
        raise SystemExit("file mismatch " + r["file"])
    values = struct.unpack("<960e", raw)
    if any(not math.isfinite(v) for v in values):
        raise SystemExit("non-finite " + r["file"])
if len(seen) != 2 * 35 * 30:
    raise SystemExit("missing keys")
print(json.dumps({"status": "QKV_MANIFEST_OK", "records": len(records),
                  "prompts": 2, "positions": 35, "layers": 30,
                  "files_verified": len(records)}, indent=2))
