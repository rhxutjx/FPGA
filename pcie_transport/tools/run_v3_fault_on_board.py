#!/usr/bin/env python3
"""v3 board fault-injection smoke: invalid CRC / session / non-finite QKV.

Each case must enter FAULT, then CONTROL.SOFT_RESET must restore READY, then
a fresh RESET+TEST must pass. This is still not an Attention numeric test.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import multisession_v3 as codec
import plan_b_status_v3 as pb
from run_v3_smoke_on_board import (
    ANLOGIC_IOCW, CONTROL_NODE, _poll_ready, _read_exact, _read_reg,
    _status, _write_deadline, _write_reg, SmokeError,
)


def _flip_crc(frame: bytes) -> bytes:
    body = bytearray(frame)
    body[24] ^= 0xFF
    return bytes(body)


def _set_session_valid_crc(frame: bytes, session: int) -> bytes:
    body = bytearray(frame)
    body[9] = session
    header = bytes(body[:codec.HEADER_BYTES])
    payload = bytes(body[codec.HEADER_BYTES:])
    crc = codec._frame_crc(header, payload)
    struct.pack_into("<I", body, 24, crc)
    return bytes(body)


def _test_payload() -> bytes:
    return bytes((7 + 13 * i) & 0xFF for i in range(1920))


def _send_reset_and_test(ctrl: int, status_offset: int, control_offset: int,
                         timeout_s: float, seq_start: int) -> int:
    seq = seq_start
    reset = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE, layer=255,
                               position=0, session_id=255, payload=b"")
    if _write_deadline(reset, timeout_s) != len(reset):
        raise SmokeError("short RESET write")
    ack = _read_exact(32, timeout_s)
    ack_header, ack_payload = codec.unpack_frame(ack, direction="c2h")
    if (ack_header.op != codec.OP_RESET_CACHE or ack_header.seq != seq
            or ack_header.session_id != 255 or ack_header.layer != 255
            or ack_header.position != 0 or ack_payload):
        raise SmokeError("RESET ACK mismatch after SOFT_RESET")
    seq += 1
    payload = _test_payload()
    test = codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0, position=0,
                              session_id=0, payload=payload)
    if _write_deadline(test, timeout_s) != len(test):
        raise SmokeError("short TEST write")
    response = _read_exact(1184, timeout_s)
    header, response_payload = codec.unpack_frame(response, direction="c2h")
    if (header.op != codec.OP_TEST or header.seq != seq or header.session_id != 0
            or header.layer != 0 or header.position != 0
            or response_payload != payload[:1152]):
        raise SmokeError("TEST mismatch after SOFT_RESET")
    _write_reg(ctrl, 0, control_offset, 1 << 2)
    _poll_ready(ctrl, status_offset, timeout_s)
    return seq + 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="v3 fault injection + SOFT_RESET recovery")
    parser.add_argument("--faults", default="bad_crc,invalid_session,nan")
    parser.add_argument("--status-offset", type=lambda s: int(s, 0), default=0xA4)
    parser.add_argument("--control-offset", type=lambda s: int(s, 0), default=0xA8)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--skip-soft-reset", action="store_true",
                        help="record FAULT and exit; recover the endpoint externally")
    parser.add_argument("--reset-first", action="store_true",
                        help="send a valid global RESET_CACHE before the fault frame")
    args = parser.parse_args(argv)

    faults = [item.strip() for item in args.faults.split(",") if item.strip()]
    allowed = {"bad_crc", "invalid_session", "nan"}
    if not faults or any(item not in allowed for item in faults):
        raise SystemExit(f"faults must be a nonempty subset of {sorted(allowed)}")

    ctrl = os.open(CONTROL_NODE, os.O_RDWR)
    seq = 1000
    records = []
    try:
        version_raw = _read_reg(ctrl, 0, 0xAC)
        status_raw, status = _status(ctrl, args.status_offset)
        print(f"VERSION 0xac=0x{version_raw:08x} STATUS=0x{status_raw:08x}", flush=True)
        if not pb.ready(status):
            raise SmokeError("initial endpoint not READY")

        if args.reset_first:
            reset = codec.pack_request(seq=seq, op=codec.OP_RESET_CACHE,
                                       layer=255, position=0, session_id=255,
                                       payload=b"")
            if _write_deadline(reset, args.timeout_s) != len(reset):
                raise SmokeError("short pre-fault RESET write")
            ack = _read_exact(32, args.timeout_s)
            ack_header, ack_payload = codec.unpack_frame(ack, direction="c2h")
            if (ack_header.op != codec.OP_RESET_CACHE or ack_header.seq != seq
                    or ack_header.session_id != 255 or ack_header.layer != 255
                    or ack_header.position != 0 or ack_payload):
                raise SmokeError("pre-fault RESET ACK mismatch")
            seq += 1
            _poll_ready(ctrl, args.status_offset, args.timeout_s)
            print(f"PRE_RESET seq={seq - 1} ACK_OK", flush=True)

        for fault in faults:
            base = codec.pack_request(seq=seq, op=codec.OP_TEST, layer=0,
                                      position=0, session_id=0,
                                      payload=_test_payload())
            if fault == "bad_crc":
                frame = _flip_crc(base)
            elif fault == "invalid_session":
                frame = _set_session_valid_crc(base, 3)
            else:
                payload = bytearray(1920)
                payload[0:2] = b"\x00\x7e"  # FP16 NaN
                frame = codec.pack_request(seq=seq, op=codec.OP_ATTENTION,
                                           layer=0, position=0, session_id=0,
                                           payload=bytes(payload))
            written = _write_deadline(frame, args.timeout_s)
            if written != len(frame):
                raise SmokeError(f"short fault frame write {written}/{len(frame)}")
            import time
            time.sleep(0.2)
            fault_raw, fault_status = _status(ctrl, args.status_offset)
            print(f"FAULT {fault} seq={seq} status=0x{fault_raw:08x} "
                  f"fault={fault_status.fault} err={fault_status.err} "
                  f"done={fault_status.done}", flush=True)
            if not fault_status.fault:
                raise SmokeError(f"{fault} did not enter FAULT")
            records.append({
                "fault": fault, "seq": seq, "status_raw": fault_raw,
                "fault": fault_status.fault, "err": fault_status.err,
                "fault_code": fault_status.fault_code,
                "last_session": fault_status.last_session,
            })
            if args.skip_soft_reset:
                break
            _write_reg(ctrl, 0, args.control_offset, 1)
            ready_raw, ready_status = _poll_ready(ctrl, args.status_offset, args.timeout_s)
            print(f"SOFT_RESET after {fault} status=0x{ready_raw:08x}", flush=True)
            seq = _send_reset_and_test(ctrl, args.status_offset,
                                       args.control_offset, args.timeout_s, seq + 1)
            print(f"RECOVERY {fault} RESET+TEST OK next_seq={seq}", flush=True)

        summary = {
            "schema": "V3_BOARD_FAULT_V1",
            "result": "FAULT_ONLY" if args.skip_soft_reset else "FAULT_RECOVERY_OK",
            "version_raw": version_raw,
            "status_initial_raw": status_raw,
            "status_offset": args.status_offset,
            "control_offset": args.control_offset,
            "records": records,
        }
        print(json.dumps(summary, indent=2), flush=True)
        if args.out is not None:
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        summary = {
            "schema": "V3_BOARD_FAULT_V1",
            "result": "FAULT_RECOVERY_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "records": records,
        }
        print(json.dumps(summary, indent=2), flush=True)
        if args.out is not None:
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 1
    finally:
        os.close(ctrl)


if __name__ == "__main__":
    raise SystemExit(main())
