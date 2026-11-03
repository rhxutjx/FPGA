"""Generate DRAFT v3 positive/negative wire vectors and SHA256 values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import multisession_v3 as codec

HERE = Path(__file__).resolve().parent
OUT = HERE / "golden_vectors_v3.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pattern(size: int, seed: int) -> bytes:
    return bytes((seed + 7 + 13 * i) & 0xFF for i in range(size))


def header_offsets():
    return {item["field"]: (item["offset"], item["size"]) for item in codec.HEADER_LAYOUT}


def rewrite(raw: bytes, **changes) -> bytes:
    body = bytearray(raw)
    offsets = header_offsets()
    for field, value in changes.items():
        offset, size = offsets[field]
        if size == 1:
            body[offset] = value
        elif size == 2:
            if isinstance(value, (bytes, bytearray)):
                body[offset:offset + size] = value
            else:
                struct.pack_into("<H", body, offset, value)
        elif size == 4:
            if isinstance(value, (bytes, bytearray)):
                body[offset:offset + size] = value
            else:
                struct.pack_into("<I", body, offset, value)
        else:
            raise ValueError(field)
    payload = bytes(body[codec.HEADER_BYTES:])
    body[24:28] = bytes(4)
    crc = codec._frame_crc(bytes(body[:codec.HEADER_BYTES]), payload)
    struct.pack_into("<I", body, 24, crc)
    return bytes(body)


def main() -> None:
    q0 = pattern(1920, 0)
    q1 = pattern(1920, 1)
    q2 = pattern(1920, 2)
    q3 = pattern(1920, 3)
    q4 = pattern(1920, 4)

    req_reset = codec.pack_request(seq=1, op=codec.OP_RESET_CACHE, layer=255,
                                   position=0, session_id=255, payload=b"")
    req_att0 = codec.pack_request(seq=2, op=codec.OP_ATTENTION, layer=0,
                                  position=0, session_id=0, payload=q0)
    req_att1 = codec.pack_request(seq=3, op=codec.OP_ATTENTION, layer=0,
                                  position=0, session_id=1, payload=q1)
    req_test2 = codec.pack_request(seq=4, op=codec.OP_TEST, layer=0,
                                   position=0, session_id=2, payload=q2)
    req_att_boundary = codec.pack_request(seq=5, op=codec.OP_ATTENTION, layer=29,
                                          position=255, session_id=2, payload=q3)
    req_test_boundary = codec.pack_request(seq=6, op=codec.OP_TEST, layer=29,
                                           position=255, session_id=0, payload=q4)

    resp_reset = codec.pack_response(seq=1, op=codec.OP_RESET_CACHE, layer=255,
                                     position=0, session_id=255, payload=b"")
    resp_att0 = codec.pack_response(seq=2, op=codec.OP_ATTENTION, layer=0,
                                    position=0, session_id=0, payload=pattern(1152, 100))
    resp_att1 = codec.pack_response(seq=3, op=codec.OP_ATTENTION, layer=0,
                                    position=0, session_id=1, payload=pattern(1152, 101))
    resp_test2 = codec.pack_response(seq=4, op=codec.OP_TEST, layer=0,
                                     position=0, session_id=2, payload=q2[:1152])
    resp_att_boundary = codec.pack_response(seq=5, op=codec.OP_ATTENTION, layer=29,
                                            position=255, session_id=2, payload=pattern(1152, 102))
    resp_test_boundary = codec.pack_response(seq=6, op=codec.OP_TEST, layer=29,
                                             position=255, session_id=0, payload=q4[:1152])

    positives = [
        ("reset_request", "h2c", req_reset, "global RESET; session=255 layer=255 seq=1"),
        ("attention_s0_request", "h2c", req_att0, "ATTENTION session0 layer0 pos0; 1920-byte test pattern"),
        ("attention_s1_request", "h2c", req_att1, "ATTENTION session1 layer0 pos0; independent payload"),
        ("test_s2_request", "h2c", req_test2, "TEST session2 layer0 pos0; 1920-byte test pattern"),
        ("attention_s2_boundary_request", "h2c", req_att_boundary, "ATTENTION session2 layer29 pos255"),
        ("test_s0_boundary_request", "h2c", req_test_boundary, "TEST session0 layer29 pos255"),
        ("reset_ack", "c2h", resp_reset, "global RESET ACK; session=255; no payload"),
        ("attention_s0_response", "c2h", resp_att0, "protocol-test response payload; NOT board Attention output"),
        ("attention_s1_response", "c2h", resp_att1, "protocol-test response payload; NOT board Attention output"),
        ("test_s2_response", "c2h", resp_test2, "TEST response = first 1152 bytes of H2C payload"),
        ("attention_s2_boundary_response", "c2h", resp_att_boundary, "protocol-test boundary response; NOT board output"),
        ("test_s0_boundary_response", "c2h", resp_test_boundary, "TEST response = first 1152 bytes of H2C payload"),
    ]

    negatives = []

    def neg(name, raw, expected, description):
        negatives.append({
            "name": name,
            "direction": "h2c",
            "hex": raw.hex(),
            "sha256": sha256(raw),
            "expected_error": expected,
            "description": description,
        })

    neg("old_v2_header", rewrite(req_att0, version=2), "bad version",
        "32-byte v3 layout but version=2; must be rejected without fallback")
    neg("invalid_session_3", rewrite(req_att0, session_id=3), "invalid session_id",
        "session 3 is outside 0..2")
    neg("attention_control_session_255", rewrite(req_att0, session_id=255),
        "invalid session_id", "255 is RESET-only and must not address KV")
    neg("reset_with_session_0", rewrite(req_reset, session_id=0),
        "RESET requires session_id=255", "RESET must use 255, not a KV session")
    neg("reset_with_layer_0", rewrite(req_reset, layer=0),
        "RESET requires layer=255", "RESET layer must be 255")
    neg("flags_nonzero", rewrite(req_att0, flags=1), "flags must be zero",
        "flags are reserved zero in v3 draft")
    neg("padding0_nonzero", rewrite(req_att0, padding0=b"\x00\x01"),
        "nonzero padding/reserved", "offset 10..11 must be zero")
    neg("reserved_nonzero", rewrite(req_att0, reserved=b"\x00\x00\x00\x01"),
        "nonzero padding/reserved", "offset 28..31 must be zero")
    neg("wrong_payload_len", rewrite(req_att0, payload_len=0),
        "wrong payload_len", "ATTENTION H2C payload length must be 1920")
    neg("seq_zero", rewrite(req_att0, seq=0), "seq must be nonzero",
        "seq=0 is reserved for no request")
    bad_crc = bytearray(req_att0)
    bad_crc[24] ^= 0xFF
    neg("bad_crc", bytes(bad_crc), "bad CRC", "flipped CRC byte; payload unchanged")
    neg("short_frame", req_att0[:31], "short frame", "truncated header")

    mismatch = bytearray(resp_att0)
    mismatch = bytearray(rewrite(bytes(mismatch), seq=99))
    negatives.append({
        "name": "response_seq_mismatch",
        "direction": "c2h",
        "hex": bytes(mismatch).hex(),
        "sha256": sha256(bytes(mismatch)),
        "expected_error": "response seq mismatch",
        "description": "response seq does not match request; host must fail-stop",
    })

    out = {
        "contract": "contract_v3_session.json",
        "contract_sha256": sha256((HERE / "contract_v3_session.json").read_bytes()),
        "codec": "multisession_v3.py",
        "codec_sha256": sha256((HERE / "multisession_v3.py").read_bytes()),
        "status": "DRAFT_NOT_FROZEN_NOT_BOARD_VERIFIED",
        "warning": "Response payloads marked 'protocol-test' are NOT FPGA Attention or KV outputs.",
        "positives": [
            {
                "name": name,
                "direction": direction,
                "hex": raw.hex(),
                "bytes": len(raw),
                "sha256": sha256(raw),
                "description": description,
            }
            for name, direction, raw, description in positives
        ],
        "negatives": negatives,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(positives)} positive, {len(negatives)} negative)")


if __name__ == "__main__":
    main()
