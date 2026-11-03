#!/usr/bin/env python3
"""Board v3 RESET/TEST smoke test over the existing SGDMA nodes.

Read-only status/version is always used. CONTROL.ACK_DONE is written only
when --ack-done is supplied. No Attention, no KV mutation, no performance claim.

Run on the board after B reports the v3 bit is loaded.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import select
import signal
import struct
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import multisession_v3 as codec
import plan_b_status_v3 as pb

ANLOGIC_IOCR = (2 << 30) | (16 << 16) | (ord("x") << 8) | 5
ANLOGIC_IOCW = (1 << 30) | (16 << 16) | (ord("x") << 8) | 4
CONTROL_NODE = "/dev/ANLOGIC-PCI0_control"
H2C_NODE = "/dev/ANLOGIC-PCI0_h2c_0"
C2H_NODE = "/dev/ANLOGIC-PCI0_c2h_0"


class SmokeError(RuntimeError):
    pass


class _Deadline(Exception):
    pass


def _read_reg(fd: int, bar: int, offset: int) -> int:
    buf = bytearray(16)
    struct.pack_into("<HHIII", buf, 0, bar, 0, offset, 0, 0)
    fcntl.ioctl(fd, ANLOGIC_IOCR, buf, True)
    return struct.unpack_from("<I", buf, 12)[0]


def _write_reg(fd: int, bar: int, offset: int, value: int) -> None:
    req = struct.pack("<HHIII", bar, 0, offset, value, 0)
    fcntl.ioctl(fd, ANLOGIC_IOCW, req)


def _status(fd: int, offset: int) -> tuple[int, pb.Status]:
    raw = _read_reg(fd, 0, offset)
    return raw, pb.decode_status(raw)


def _write_deadline(frame: bytes, timeout_s: float) -> int:
    fd = os.open(H2C_NODE, os.O_WRONLY)
    try:
        def _alarm(signum, frame_):
            raise _Deadline()
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            return os.write(fd, frame)
        except _Deadline as exc:
            raise SmokeError("H2C write deadline expired; endpoint needs reset") from exc
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
    finally:
        os.close(fd)


def _read_exact(count: int, timeout_s: float) -> bytes:
    fd = os.open(C2H_NODE, os.O_RDONLY | os.O_NONBLOCK)
    deadline = time.monotonic() + timeout_s
    out = bytearray()
    try:
        while len(out) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SmokeError(f"C2H timeout at {len(out)}/{count}")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise SmokeError(f"C2H read timeout at {len(out)}/{count}")
            chunk = os.read(fd, count - len(out))
            if chunk:
                out += chunk
        return bytes(out)
    finally:
        os.close(fd)


def _drain(timeout_s: float = 0.2) -> int:
    fd = os.open(C2H_NODE, os.O_RDONLY | os.O_NONBLOCK)
    total = 0
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
    finally:
        os.close(fd)
    return total


def _poll_ready(fd: int, status_offset: int, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        raw, status = _status(fd, status_offset)
        last = (raw, status)
        if status.fault:
            raise SmokeError(f"FAULT while polling READY: status=0x{raw:08x}")
        if pb.ready(status):
            return last
        time.sleep(0.002)
    raise SmokeError(f"READY timeout; last status=0x{last[0]:08x}")


def _payload(seed: int) -> bytes:
    return bytes((seed + 7 + 13 * i) & 0xFF for i in range(1920))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="v3 RESET/TEST board smoke")
    parser.add_argument("--status-offset", type=lambda s: int(s, 0), default=0xA4)
    parser.add_argument("--control-offset", type=lambda s: int(s, 0), default=0xA8)
    parser.add_argument("--version-offset", type=lambda s: int(s, 0), default=0xAC)
    parser.add_argument("--rounds", type=int, default=1,
                        help="TEST rounds per session (start with 1)")
    parser.add_argument("--sessions", default="0")
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument("--ack-done", action="store_true",
                        help="write CONTROL.ACK_DONE after a successful TEST")
    parser.add_argument("--ack-pending", action="store_true",
                        help="clear a DONE left by a previous process before starting")
    parser.add_argument("--interleave", action="store_true",
                        help="round-robin sessions instead of finishing one session first")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    sessions = [int(x, 0) for x in args.sessions.split(",") if x.strip()]
    if not sessions or any(s not in (0, 1, 2) for s in sessions):
        raise SystemExit("sessions must be a nonempty subset of 0,1,2")
    if args.rounds < 1:
        raise SystemExit("rounds must be >= 1")

    ctrl = os.open(CONTROL_NODE, os.O_RDWR)
    records = []
    try:
        version_raw = _read_reg(ctrl, 0, args.version_offset)
        status_raw, status = _status(ctrl, args.status_offset)
        print(f"VERSION 0x{args.version_offset:x}=0x{version_raw:08x}", flush=True)
        print(f"STATUS 0x{args.status_offset:x}=0x{status_raw:08x} "
              f"ready={status.ready} fault={status.fault} busy={status.busy} "
              f"done={status.done} reset_busy={status.reset_busy} err={status.err}",
              flush=True)
        if status.fault:
            raise SmokeError("endpoint already FAULT; do not send H2C")
        if status.done:
            if not args.ack_pending:
                raise SmokeError("DONE already set; rerun with --ack-pending or recover")
            print("ACK_PENDING clearing DONE", flush=True)
            _write_reg(ctrl, 0, args.control_offset, 1 << 2)
            status_raw, status = _poll_ready(ctrl, args.status_offset, args.timeout_s)
            print(f"ACK_PENDING status=0x{status_raw:08x}", flush=True)
        if not pb.ready(status):
            raise SmokeError("endpoint not READY; no H2C sent")

        seq = 1
        reset = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                                   position=0, session_id=255, payload=b"")
        print(f"RESET writing {len(reset)} bytes seq={seq}", flush=True)
        written = _write_deadline(reset, args.timeout_s)
        print(f"RESET write returned {written}", flush=True)
        if written != len(reset):
            raise SmokeError(f"short RESET write {written}/{len(reset)}")
        print("RESET waiting ACK", flush=True)
        ack = _read_exact(32, args.timeout_s)
        ack_header, ack_payload = codec.unpack_frame(ack, direction="c2h")
        if (ack_header.op != codec.OP_RESET_CACHE or ack_header.seq != seq
                or ack_header.session_id != 255 or ack_header.layer != 255
                or ack_header.position != 0 or ack_payload):
            raise SmokeError("RESET ACK mismatch")
        print(f"RESET seq={seq} ACK_OK status=0x{_status(ctrl, args.status_offset)[0]:08x}", flush=True)
        seq += 1

        if args.interleave:
            plan = [(session, round_index)
                    for round_index in range(args.rounds)
                    for session in sessions]
        else:
            plan = [(session, round_index)
                    for session in sessions
                    for round_index in range(args.rounds)]
        for session, round_index in plan:
            _poll_ready(ctrl, args.status_offset, args.timeout_s)
            payload = _payload(10 * session + round_index)
            frame = codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0,
                                       position=0, session_id=session,
                                       payload=payload)
            written = _write_deadline(frame, args.timeout_s)
            if written != len(frame):
                raise SmokeError(f"short TEST write {written}/{len(frame)}")
            response = _read_exact(1184, args.timeout_s)
            response_header, response_payload = codec.unpack_frame(response, direction="c2h")
            if (response_header.op != codec.OP_TEST or response_header.seq != seq
                    or response_header.session_id != session
                    or response_header.layer != 0 or response_header.position != 0):
                raise SmokeError("TEST response header mismatch")
            if response_payload != payload[:1152]:
                raise SmokeError("TEST payload mismatch")
            raw_status, test_status = _status(ctrl, args.status_offset)
            print(f"TEST session={session} seq={seq} OK status=0x{raw_status:08x} "
                  f"done={test_status.done} err={test_status.err} fault={test_status.fault}",
                  flush=True)
            records.append({
                "session": session, "seq": seq, "status_raw": raw_status,
                "done": test_status.done, "err": test_status.err,
                "fault": test_status.fault,
            })
            if args.ack_done:
                if not test_status.done:
                    raise SmokeError("ACK_DONE requested but DONE=0")
                _write_reg(ctrl, 0, args.control_offset, 1 << 2)
                ack_raw, ack_status = _poll_ready(ctrl, args.status_offset, args.timeout_s)
                print(f"ACK_DONE session={session} status=0x{ack_raw:08x}", flush=True)
            seq += 1

        summary = {
            "schema": "V3_BOARD_SMOKE_V1",
            "version_raw": version_raw,
            "status_initial_raw": status_raw,
            "sessions": sessions,
            "rounds_per_session": args.rounds,
            "interleave": bool(args.interleave),
            "ack_done": bool(args.ack_done),
            "status_offset": args.status_offset,
            "control_offset": args.control_offset,
            "version_offset": args.version_offset,
            "records": records,
            "result": "SMOKE_OK",
        }
        print(json.dumps(summary, indent=2), flush=True)
        if args.out is not None:
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        summary = {
            "schema": "V3_BOARD_SMOKE_V1",
            "result": "SMOKE_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "sessions": sessions,
            "rounds_per_session": args.rounds,
            "ack_done": bool(args.ack_done),
            "records": records,
        }
        print(json.dumps(summary, indent=2), flush=True)
        return 1
    finally:
        os.close(ctrl)


if __name__ == "__main__":
    raise SystemExit(main())


