#!/usr/bin/env python3
"""Validate a 2/3-prompt QKV manifest produced on the board."""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
records = manifest["records_list"]
prompt_count = len(manifest["prompts"])
expected = prompt_count * 35 * 30
if prompt_count not in (2, 3) or manifest["records"] != expected or len(records) != expected:
    raise SystemExit("wrong record count")
if len(manifest["prompts"]) != prompt_count:
    raise SystemExit("wrong prompt count")
if any(len(p["token_ids"]) != 35 for p in manifest["prompts"]):
    raise SystemExit("wrong token count")
seen = set()
for r in records:
    key = (r["request"], r["position"], r["layer"])
    if key in seen:
        raise SystemExit("duplicate " + repr(key))
    seen.add(key)
    if not (0 <= r["request"] < prompt_count and 0 <= r["position"] < 35 and 0 <= r["layer"] < 30):
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
if len(seen) != expected:
    raise SystemExit("missing keys")
print(json.dumps({"status": "QKV_MANIFEST_OK", "records": len(records),
                  "prompts": prompt_count, "positions": 35, "layers": 30,
                  "files_verified": len(records)}, indent=2))



