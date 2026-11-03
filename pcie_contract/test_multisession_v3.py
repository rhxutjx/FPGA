"""Offline tests for the DRAFT v3 multi-session codec and wire vectors.

Run:  python -m unittest test_multisession_v3 -v
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

import multisession_v3 as codec

HERE = Path(__file__).resolve().parent
GOLDEN = json.loads((HERE / "golden_vectors_v3.json").read_text(encoding="utf-8"))
CONTRACT = json.loads((HERE / "contract_v3_session.json").read_text(encoding="utf-8"))


def by_name(name):
    for item in GOLDEN["positives"]:
        if item["name"] == name:
            return item
    raise KeyError(name)


def frame(name):
    return bytes.fromhex(by_name(name)["hex"])


class ContractV3Tests(unittest.TestCase):
    def test_contract_core_fields(self):
        self.assertEqual(CONTRACT["protocol_version"], 3)
        self.assertEqual(CONTRACT["max_sessions"], 3)
        self.assertEqual(CONTRACT["session_ids"], [0, 1, 2])
        self.assertEqual(CONTRACT["control_session_id"], 255)
        self.assertEqual(CONTRACT["max_inflight"], 1)
        self.assertTrue(CONTRACT["single_inflight"])
        self.assertTrue(CONTRACT["global_reset"])
        self.assertFalse(CONTRACT["per_session_reset"])
        self.assertEqual(CONTRACT["capability_status"], "DEFERRED_NOT_IN_V3")
        self.assertEqual(CONTRACT["session_stride_bytes"], {"B": 5898240, "M": 1966080})

    def test_header_offsets(self):
        layout = {f["field"]: f for f in CONTRACT["header_layout"]}
        self.assertEqual(layout["session_id"]["offset"], 9)
        self.assertEqual(layout["version"]["offset"], 4)
        self.assertEqual(layout["layer"]["offset"], 8)
        self.assertEqual(layout["crc32"]["offset"], 24)
        self.assertEqual(CONTRACT["header_bytes"], 32)

    def test_crc_check_value(self):
        import zlib
        self.assertEqual(zlib.crc32(b"123456789") & 0xFFFFFFFF, 0xCBF43926)

    def test_reset_wire_exact(self):
        raw = frame("reset_request")
        self.assertEqual(len(raw), 32)
        self.assertEqual(raw[:4].hex(), "4b564d58")
        self.assertEqual(raw[4:6], b"\x03\x00")
        self.assertEqual(raw[6], 1)
        self.assertEqual(raw[8], 255)
        self.assertEqual(raw[9], 255)
        header, payload = codec.unpack_frame(raw, direction="h2c")
        self.assertEqual(header.session_id, 255)
        self.assertEqual(header.layer, 255)
        self.assertEqual(payload, b"")
        self.assertEqual(header.crc32, 0x0B0C2BBA)

    def test_attention_zero_copy_roundtrip(self):
        raw = frame("attention_s0_request")
        self.assertEqual(len(raw), 1952)
        header, payload = codec.unpack_frame(raw, direction="h2c")
        self.assertEqual(header.version, 3)
        self.assertEqual(header.session_id, 0)
        self.assertEqual(header.position, 0)
        self.assertEqual(header.payload_len, 1920)
        self.assertEqual(len(payload), 1920)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), by_name("attention_s0_request")["sha256"])

    def test_all_positive_vectors_parse(self):
        for item in GOLDEN["positives"]:
            raw = bytes.fromhex(item["hex"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
            self.assertEqual(len(raw), item["bytes"])
            codec.unpack_frame(raw, direction=item["direction"])

    def test_reset_ack_matches_request(self):
        request = codec.unpack_frame(frame("reset_request"), direction="h2c")[0]
        payload = codec.check_response(request, frame("reset_ack"))
        self.assertEqual(payload, b"")

    def test_attention_response_echo(self):
        request = codec.unpack_frame(frame("attention_s0_request"), direction="h2c")[0]
        payload = codec.check_response(request, frame("attention_s0_response"))
        self.assertEqual(len(payload), 1152)
        self.assertEqual(payload, bytes((100 + 7 + 13 * i) & 0xFF for i in range(1152)))

    def test_test_response_is_first_half(self):
        request = codec.unpack_frame(frame("test_s2_request"), direction="h2c")
        payload = codec.check_response(request[0], frame("test_s2_response"))
        self.assertEqual(payload, request[1][:1152])

    def test_boundary_responses(self):
        for req_name, resp_name in [
            ("attention_s2_boundary_request", "attention_s2_boundary_response"),
            ("test_s0_boundary_request", "test_s0_boundary_response"),
        ]:
            request = codec.unpack_frame(frame(req_name), direction="h2c")[0]
            codec.check_response(request, frame(resp_name))

    def test_negative_vectors(self):
        positive = frame("attention_s0_request")
        for item in GOLDEN["negatives"]:
            raw = bytes.fromhex(item["hex"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
            if item["name"] == "response_seq_mismatch":
                request = codec.unpack_frame(positive, direction="h2c")[0]
                with self.assertRaises(codec.FrameError) as ctx:
                    codec.check_response(request, raw)
            else:
                with self.assertRaises(codec.FrameError) as ctx:
                    codec.unpack_frame(raw, direction=item["direction"])
            self.assertIn(item["expected_error"], str(ctx.exception), item["name"])

    def test_forbidden_sessions_rejected(self):
        payload = bytes(1920)
        for session in (3, 4, 254, 255):
            with self.assertRaises(codec.FrameError):
                codec.pack_request(seq=10, op=codec.OP_ATTENTION, layer=0,
                                   position=0, session_id=session, payload=payload)

    def test_v2_rejected(self):
        raw = bytearray(frame("attention_s0_request"))
        raw[4:6] = (2).to_bytes(2, "little")
        with self.assertRaises(codec.FrameError):
            codec.unpack_frame(bytes(raw), direction="h2c")

    def test_corrupt_crc_rejected(self):
        raw = bytearray(frame("attention_s0_request"))
        raw[24] ^= 0xFF
        with self.assertRaises(codec.FrameError):
            codec.unpack_frame(bytes(raw), direction="h2c")

    def test_unknown_op_rejected(self):
        raw = bytearray(frame("attention_s0_request"))
        raw[6] = 3
        with self.assertRaises(codec.FrameError):
            codec.unpack_frame(bytes(raw), direction="h2c")


if __name__ == "__main__":
    unittest.main()
