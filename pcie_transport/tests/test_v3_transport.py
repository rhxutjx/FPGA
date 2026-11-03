"""Offline tests for the v3 session transport and batch scheduler."""
from __future__ import annotations

import time
import unittest

import multisession_v3 as codec
import plan_b_status_v3 as pb
from pcie_transport.v3_transport import (
    BatchItem, PlanBStatusController, SessionBatchScheduler, V3Transport,
    V3TransportError,
)


class MockStatus:
    def __init__(self):
        self.ready = 1
        self.done = 0
        self.fault = 0
        self.err = 0

    def _status(self):
        return pb.Status(ready=self.ready, done=self.done, fault=self.fault,
                         err=self.err, fault_code=0, last_session=255)

    def poll_ready(self, deadline):
        if self.fault:
            raise V3TransportError("fault")
        if not self.ready:
            raise V3TransportError("not ready")
        return self._status()

    def poll_done(self, deadline):
        if self.fault:
            raise V3TransportError("fault")
        if not self.done:
            raise V3TransportError("not done")
        return self._status()

    def ack_done(self):
        self.done = 0
        self.ready = 1

    def soft_reset(self):
        self.fault = 0
        self.done = 0
        self.ready = 1


class MockDevice:
    def __init__(self, status):
        self.status = status
        self.frames = []
        self.responses = []
        self.fail_next = False
        self.writes = 0

    def write(self, frame, *, deadline):
        self.writes += 1
        if self.fail_next:
            self.fail_next = False
            self.status.ready = 0
            self.status.fault = 1
            self.status.err = 7
            raise V3TransportError("injected write failure")
        header, payload = codec.unpack_frame(frame, direction="h2c")
        self.frames.append((header, payload))
        if header.op == codec.OP_RESET_CACHE:
            response = codec.pack_response(seq=header.seq, op=header.op,
                                           layer=header.layer, position=header.position,
                                           session_id=header.session_id, payload=b"")
            self.status.ready = 1
            self.status.done = 0
        elif header.op == codec.OP_TEST:
            response = codec.pack_response(seq=header.seq, op=header.op,
                                           layer=header.layer, position=header.position,
                                           session_id=header.session_id,
                                           payload=payload[:1152])
            self.status.ready = 0
            self.status.done = 1
        else:
            response = codec.pack_response(seq=header.seq, op=header.op,
                                           layer=header.layer, position=header.position,
                                           session_id=header.session_id,
                                           payload=bytes(1152))
            self.status.ready = 0
            self.status.done = 1
        self.responses.append(response)
        return len(frame)

    def read_exact(self, count, *, deadline):
        if not self.responses:
            raise V3TransportError("no response")
        raw = self.responses.pop(0)
        if len(raw) != count:
            raise V3TransportError("wrong response size")
        return raw

    def flush_queues(self):
        self.responses.clear()


def make():
    status = MockStatus()
    device = MockDevice(status)
    return status, device, V3Transport(device, status)


class V3TransportTests(unittest.TestCase):
    def test_reset_test_session(self):
        status, device, transport = make()
        reset = transport.reset_all()
        self.assertEqual(reset.session, 255)
        self.assertEqual(len(device.frames), 1)
        payload = bytes((i * 3) & 0xFF for i in range(1920))
        result = transport.test(0, payload)
        self.assertEqual(result.session, 0)
        self.assertEqual(result.payload, payload[:1152])
        self.assertEqual(status.ready, 1)
        self.assertEqual(status.done, 0)
        self.assertEqual(transport.next_seq, 3)

    def test_sessions_are_routed(self):
        status, device, transport = make()
        transport.reset_all()
        for session in (0, 1, 2):
            payload = bytes([session + 1]) * 1920
            out = transport.test(session, payload)
            self.assertEqual(out.session, session)
            self.assertEqual(device.frames[-1][0].session_id, session)
            self.assertEqual(out.payload, payload[:1152])

    def test_attention_requires_reset(self):
        status, device, transport = make()
        with self.assertRaises(V3TransportError):
            transport.attention(0, 0, 0, bytes(1920))
        self.assertEqual(device.writes, 0)
        transport.reset_all()
        result = transport.attention(0, 0, 0, bytes(1920))
        self.assertEqual(len(result.payload), 1152)

    def test_fault_fail_stop_and_recover(self):
        status, device, transport = make()
        transport.reset_all()
        device.fail_next = True
        with self.assertRaises(V3TransportError):
            transport.test(0, bytes(1920))
        self.assertEqual(transport.state.value, "FAULT")
        with self.assertRaises(V3TransportError):
            transport.reset_all()
        transport.recover()
        self.assertTrue(transport.needs_reset)
        transport.reset_all()
        self.assertFalse(transport.needs_reset)

    def test_batch_three_sessions(self):
        status, device, transport = make()
        transport.reset_all()
        scheduler = SessionBatchScheduler(transport, max_batch=3)
        items = [BatchItem(session, 0, 0, bytes([session + 1]) * 1920)
                 for session in (0, 1, 2)]
        results = scheduler.test_batch(items)
        self.assertEqual([r.session for r in results], [0, 1, 2])
        self.assertEqual([r.payload for r in results],
                         [bytes([s + 1]) * 1152 for s in (0, 1, 2)])

    def test_batch_rejects_bad_groups(self):
        status, device, transport = make()
        transport.reset_all()
        scheduler = SessionBatchScheduler(transport, max_batch=3)
        with self.assertRaises(V3TransportError):
            scheduler.test_batch([BatchItem(0, 0, 0, bytes(1920)),
                                  BatchItem(0, 0, 0, bytes(1920))])
        with self.assertRaises(V3TransportError):
            scheduler.test_batch([BatchItem(0, 0, 0, bytes(1920)),
                                  BatchItem(1, 0, 1, bytes(1920))])
        with self.assertRaises(V3TransportError):
            scheduler.test_batch([BatchItem(3, 0, 0, bytes(1920))])

    def test_plan_b_status_controller_bits(self):
        state = {"status": pb.encode_status(pb.Status(ready=1)),
                 "controls": []}
        def read():
            return state["status"]
        def write(value):
            state["controls"].append(value)
            if value & 4:
                state["status"] = pb.encode_status(pb.Status(ready=1))
            if value & 1:
                state["status"] = pb.encode_status(pb.Status(ready=1))
        controller = PlanBStatusController(read, write)
        self.assertTrue(pb.ready(controller.poll_ready(time.monotonic() + 1)))
        controller.ack_done()
        controller.soft_reset()
        self.assertEqual(state["controls"], [4, 1])

    def test_sequence_is_not_reused(self):
        status, device, transport = make()
        transport.reset_all()
        transport.test(0, bytes(1920))
        seqs = [h.seq for h, _ in device.frames]
        self.assertEqual(seqs, sorted(set(seqs)))
        self.assertEqual(seqs, [1, 2])


if __name__ == "__main__":
    unittest.main()
