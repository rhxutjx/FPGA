"""Reusable v3 session transport and small session-batch scheduler.

This is the host-side contract for the v3 multi-session endpoint. It does NOT
bind BAR offsets and does NOT implement the NPU batch; it enforces one
in-flight frame, global RESET, per-session routing, DONE/ACK_DONE, and
FAULT fail-stop around a DeviceOps + StatusOps pair.

The hardware adapter can use the existing SGDMA nodes and a Plan B status
controller once B freezes the register binding.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Protocol

import multisession_v3 as codec
import plan_b_status_v3 as pb


class V3TransportError(RuntimeError):
    pass


class V3State(str, Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    FAULT = "FAULT"


class DeviceOps(Protocol):
    def write(self, frame: bytes, *, deadline: float) -> int: ...
    def read_exact(self, count: int, *, deadline: float) -> bytes: ...
    def flush_queues(self) -> None: ...


class StatusOps(Protocol):
    def poll_ready(self, deadline: float) -> pb.Status: ...
    def poll_done(self, deadline: float) -> pb.Status: ...
    def ack_done(self) -> None: ...
    def soft_reset(self) -> None: ...


class PlanBStatusController:
    """Map STATUS/CONTROL 32-bit accessors to the v3 state machine.

    The caller supplies the already-verified bit-level read/write functions;
    no address is hardcoded here.
    """

    def __init__(self, read_status, write_control, *, poll_s: float = 0.001):
        if poll_s <= 0:
            raise ValueError("poll_s must be positive")
        self._read = read_status
        self._write = write_control
        self.poll_s = poll_s

    def status(self) -> pb.Status:
        return pb.decode_status(self._read())

    def poll_ready(self, deadline: float) -> pb.Status:
        last = None
        while True:
            last = self.status()
            if last.fault:
                raise V3TransportError(f"endpoint FAULT before frame: status={pb.encode_status(last):08x}")
            if pb.ready(last):
                return last
            if time.monotonic() >= deadline:
                raise V3TransportError("READY deadline expired")
            time.sleep(self.poll_s)

    def poll_done(self, deadline: float) -> pb.Status:
        last = None
        while True:
            last = self.status()
            if last.fault:
                raise V3TransportError(f"endpoint FAULT waiting DONE: err={last.err}")
            if last.done:
                if last.err:
                    raise V3TransportError(f"DONE with ERR={last.err}")
                return last
            if time.monotonic() >= deadline:
                raise V3TransportError("DONE deadline expired")
            time.sleep(self.poll_s)

    def ack_done(self) -> None:
        self._write(1 << 2)

    def soft_reset(self) -> None:
        self._write(1)


@dataclass(frozen=True)
class RoundResult:
    session: int
    layer: int
    position: int
    seq: int
    payload: bytes
    status_raw: int


class V3Transport:
    def __init__(self, device: DeviceOps, status: StatusOps, *,
                 timeout_s: float = 5.0, start_seq: int = 1,
                 ack_done: bool = True):
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("finite positive timeout_s required")
        if type(start_seq) is not int or not 1 <= start_seq <= codec.MAX_SEQ:
            raise ValueError("start_seq must be nonzero u32")
        self.device = device
        self.status = status
        self.timeout_s = timeout_s
        self.next_seq = start_seq
        self.state = V3State.IDLE
        self.needs_reset = True
        self.ack_done_enabled = ack_done
        self.inflight = None

    def _deadline(self) -> float:
        return time.monotonic() + self.timeout_s

    def _fail(self, exc: Exception):
        self.state = V3State.FAULT
        self.inflight = None
        raise V3TransportError(str(exc)) from exc

    def _occupy(self, desc):
        if self.state is not V3State.IDLE or self.inflight is not None:
            raise V3TransportError("single-inflight violation")
        self.inflight = desc
        self.state = V3State.BUSY

    def _release(self):
        self.state = V3State.IDLE
        self.inflight = None

    def _next_seq(self) -> int:
        seq = self.next_seq
        if seq > codec.MAX_SEQ:
            raise V3TransportError("sequence exhausted; no wrap/reuse")
        self.next_seq += 1
        return seq

    def _write(self, frame: bytes, deadline: float):
        written = self.device.write(frame, deadline=deadline)
        if written != len(frame):
            raise V3TransportError(f"short H2C write {written}/{len(frame)}")

    def reset_all(self) -> RoundResult:
        if self.state is V3State.FAULT:
            raise V3TransportError("FAULT requires recover() before RESET")
        deadline = self._deadline()
        self.status.poll_ready(deadline)
        seq = self._next_seq()
        frame = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                                   position=0, session_id=255, payload=b"")
        self._occupy(("reset", seq, 255, 255, 0))
        try:
            self._write(frame, deadline)
            raw = self.device.read_exact(32, deadline=deadline)
            header, payload = codec.unpack_frame(raw, direction="c2h")
            if (header.op != codec.OP_RESET_CACHE or header.seq != seq
                    or header.session_id != 255 or header.layer != 255
                    or header.position != 0 or payload):
                raise V3TransportError("RESET ACK mismatch")
            status_raw = pb.encode_status(self.status.poll_ready(deadline))
            self.needs_reset = False
            self._release()
            return RoundResult(255, 255, 0, seq, b"", status_raw)
        except BaseException as exc:
            self._fail(exc)

    def _request(self, op, session, layer, position, payload):
        deadline = self._deadline()
        self.status.poll_ready(deadline)
        if op == codec.OP_ATTENTION and self.needs_reset:
            raise V3TransportError("ATTENTION requires a successful global RESET")
        seq = self._next_seq()
        frame = codec.pack_request(seq=seq, op=op, layer=layer, position=position,
                                   session_id=session, payload=payload)
        self._occupy((op, seq, session, layer, position))
        try:
            self._write(frame, deadline)
            status = self.status.poll_done(deadline)
            raw = self.device.read_exact(1184, deadline=deadline)
            response_header, response_payload = codec.unpack_frame(raw, direction="c2h")
            request_header = codec.unpack_frame(frame, direction="h2c")[0]
            for field in ("op", "seq", "session_id", "layer", "position"):
                if getattr(response_header, field) != getattr(request_header, field):
                    raise V3TransportError(f"response {field} mismatch")
            if self.ack_done_enabled:
                self.status.ack_done()
                status = self.status.poll_ready(deadline)
            self._release()
            return RoundResult(session, layer, position, seq, response_payload,
                               pb.encode_status(status))
        except BaseException as exc:
            self._fail(exc)

    def test(self, session: int, payload: bytes, *, layer: int = 0,
             position: int = 0) -> RoundResult:
        if len(payload) != 1920:
            raise V3TransportError("TEST payload must be 1920 bytes")
        result = self._request(codec.OP_TEST, session, layer, position, payload)
        if result.payload != payload[:1152]:
            raise V3TransportError("TEST response payload mismatch")
        return result

    def attention(self, session: int, layer: int, position: int,
                  payload: bytes) -> RoundResult:
        if len(payload) != 1920:
            raise V3TransportError("ATTENTION payload must be 1920 bytes")
        return self._request(codec.OP_ATTENTION, session, layer, position, payload)

    def recover(self) -> None:
        self.device.flush_queues()
        self.status.soft_reset()
        self.status.poll_ready(self._deadline())
        self.needs_reset = True
        self.state = V3State.IDLE
        self.inflight = None


@dataclass(frozen=True)
class BatchItem:
    session: int
    layer: int
    position: int
    payload: bytes


class SessionBatchScheduler:
    """Host-side batch grouping for independent sessions.

    The v3 endpoint is still single-inflight; this scheduler sends the batch
    rows sequentially and returns the results. It never claims parallel FPGA
    Attention. NPU linear batching is a separate upstream layer.
    """

    def __init__(self, transport: V3Transport, *, max_batch: int = 3):
        if type(max_batch) is not int or not 1 <= max_batch <= 3:
            raise ValueError("max_batch must be 1..3")
        self.transport = transport
        self.max_batch = max_batch

    def test_batch(self, items: list[BatchItem]) -> list[RoundResult]:
        self._validate(items)
        return [self.transport.test(item.session, item.payload,
                                    layer=item.layer, position=item.position)
                for item in items]

    def attention_batch(self, items: list[BatchItem]) -> list[RoundResult]:
        self._validate(items)
        return [self.transport.attention(item.session, item.layer,
                                         item.position, item.payload)
                for item in items]

    def _validate(self, items):
        if not items or len(items) > self.max_batch:
            raise V3TransportError("batch size out of range")
        sessions = [item.session for item in items]
        if len(set(sessions)) != len(sessions):
            raise V3TransportError("batch rows must use distinct sessions")
        if any(item.session not in (0, 1, 2) for item in items):
            raise V3TransportError("batch session must be 0..2")
        if any(len(item.payload) != 1920 for item in items):
            raise V3TransportError("batch payload must be 1920")
        if len({(item.layer, item.position) for item in items}) != 1:
            raise V3TransportError("batch rows must share layer/position")
