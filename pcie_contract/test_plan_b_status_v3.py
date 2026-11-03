"""Offline tests for the DRAFT v3 Plan B status/control logical bits.

Run:  python -m unittest test_plan_b_status_v3 -v
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import plan_b_status_v3 as pb

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "plan_b_status_v3.json").read_text(encoding="utf-8"))


class PlanBStatusV3Tests(unittest.TestCase):
    def test_ready_sample(self):
        value = 1 << 4
        status = pb.decode_status(value)
        self.assertTrue(pb.ready(status))
        self.assertEqual(pb.encode_status(status), value)
        self.assertEqual(pb.Status(ready=1).last_session, 255)
        self.assertEqual(pb.decode_status(value).last_session, 0)

    def test_done_and_err(self):
        status = pb.Status(done=1, err=0, last_session=2)
        value = pb.encode_status(status)
        self.assertEqual(status.done, 1)
        self.assertEqual(status.err, 0)
        self.assertEqual(pb.decode_status(value), status)
        self.assertEqual(pb.validate_status(status), [])

    def test_fault_code_and_session(self):
        status = pb.Status(fault=1, err=4, fault_code=4, last_session=1, reserved=0)
        value = pb.encode_status(status)
        self.assertEqual(pb.decode_status(value), status)
        self.assertEqual(pb.err_name(status), "SESSION")
        self.assertEqual(pb.fault_name(status), "SESSION")
        self.assertEqual(pb.validate_status(status), [])

    def test_all_bits_roundtrip(self):
        status = pb.Status(done=0, err=7, ready=0, fault=1, busy=0,
                           reset_busy=1, fault_code=15, last_session=3,
                           reserved=0)
        self.assertEqual(pb.decode_status(pb.encode_status(status)), status)

    def test_ready_invariant(self):
        for name, field in [("busy", "busy"), ("done", "done"),
                            ("fault", "fault"), ("reset_busy", "reset_busy")]:
            status = pb.Status(ready=1, **{field: 1, "err": 1 if field == "fault" else 0})
            self.assertFalse(pb.ready(status))
            self.assertTrue(any("READY" in item for item in pb.validate_status(status)))

    def test_fault_requires_err(self):
        status = pb.Status(fault=1, err=0)
        self.assertIn("FAULT requires ERR != 0", pb.validate_status(status))

    def test_done_requires_ok(self):
        status = pb.Status(done=1, err=3)
        self.assertIn("successful DONE requires ERR == 0", pb.validate_status(status))

    def test_reserved_status(self):
        status = pb.Status(ready=1, reserved=1)
        self.assertIn("reserved must be zero", pb.validate_status(status))

    def test_control_roundtrip(self):
        control = pb.Control(soft_reset=1, ack_done=1)
        value = pb.encode_control(control)
        self.assertEqual(value, 0b101)
        self.assertEqual(pb.decode_control(value), control)

    def test_control_reserved_rejected(self):
        with self.assertRaises(ValueError):
            pb.encode_control(pb.Control(reserved=1))
        with self.assertRaises(ValueError):
            pb.encode_control(pb.Control(soft_reset=2))

    def test_decode_ranges(self):
        with self.assertRaises(ValueError):
            pb.decode_status(-1)
        with self.assertRaises(ValueError):
            pb.decode_control(0x1_0000_0000)

    def test_spec_offsets_and_bits(self):
        self.assertEqual(SPEC["address_binding"]["status"], "UNBOUND")
        self.assertIsNone(SPEC["address_binding"]["status_offset"])
        self.assertIsNone(SPEC["address_binding"]["control_offset"])
        bits = {item.get("name"): item for item in SPEC["status_register"]["bits"]}
        self.assertEqual(bits["DONE"]["bit"], 0)
        self.assertEqual(bits["READY"]["bit"], 4)
        self.assertEqual(bits["FAULT"]["bit"], 5)
        self.assertEqual(bits["BUSY"]["bit"], 6)
        self.assertEqual(bits["RESET_BUSY"]["bit"], 7)
        self.assertEqual(bits["ERR"]["bits"], [1, 3])
        self.assertEqual(bits["FAULT_CODE"]["bits"], [8, 15])
        self.assertEqual(bits["LAST_SESSION"]["bits"], [16, 23])
        control = {item.get("name"): item["bit"] for item in SPEC["control_register"]["bits"] if "bit" in item}
        self.assertEqual(control, {"SOFT_RESET": 0, "ABORT_BATCH": 1, "ACK_DONE": 2})

    def test_no_per_session_status(self):
        self.assertIn("no per-session", SPEC["scope"])
        self.assertEqual(SPEC["status_register"]["bits"][1]["name"], "ERR")
        self.assertIn("single_inflight", SPEC["transport"])
        self.assertTrue(SPEC["transport"]["single_inflight"])

    def test_reset_ack_sequence_documented(self):
        text = " ".join(SPEC["reset_sequence"])
        self.assertIn("RESET ACK", text)
        self.assertIn("32", text)
        self.assertIn("READY", text)

    def test_fault_recovery_no_auto(self):
        text = " ".join(SPEC["fault_recovery"])
        self.assertIn("auto_retry=false", text)
        self.assertIn("auto_resend=false", text)
        self.assertIn("pcie1-recover.sh", text)


if __name__ == "__main__":
    unittest.main()
