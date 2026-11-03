"""PC2 DRAFT v3 Plan B global status/control codec (logical bits only).

This module does not claim BAR offsets. It only packs/unpacks the 32-bit
status and control words defined in plan_b_status_v3.json.
"""
from dataclasses import dataclass
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = json.loads((_HERE / "plan_b_status_v3.json").read_text(encoding="utf-8"))

ERR_NAMES = _SPEC["status_register"]["err_values"]
FAULT_NAMES = _SPEC["status_register"]["fault_code_values"]
CONTROL_NAMES = {item["name"]: item["bit"] for item in _SPEC["control_register"]["bits"] if "bit" in item}


@dataclass(frozen=True)
class Status:
    done: int = 0
    err: int = 0
    ready: int = 0
    fault: int = 0
    busy: int = 0
    reset_busy: int = 0
    fault_code: int = 0
    last_session: int = 255
    reserved: int = 0


@dataclass(frozen=True)
class Control:
    soft_reset: int = 0
    abort_batch: int = 0
    ack_done: int = 0
    reserved: int = 0


def decode_status(value: int) -> Status:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("status must be u32")
    return Status(
        done=(value >> 0) & 1,
        err=(value >> 1) & 0x7,
        ready=(value >> 4) & 1,
        fault=(value >> 5) & 1,
        busy=(value >> 6) & 1,
        reset_busy=(value >> 7) & 1,
        fault_code=(value >> 8) & 0xFF,
        last_session=(value >> 16) & 0xFF,
        reserved=(value >> 24) & 0xFF,
    )


def encode_status(status: Status) -> int:
    for name in ("done", "err", "ready", "fault", "busy", "reset_busy",
                 "fault_code", "last_session", "reserved"):
        value = getattr(status, name)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"bad {name}")
    if status.err > 7 or status.fault_code > 0xFF or status.last_session > 0xFF or status.reserved > 0xFF:
        raise ValueError("field out of range")
    if any(getattr(status, name) not in (0, 1) for name in
           ("done", "ready", "fault", "busy", "reset_busy")):
        raise ValueError("flag bits must be 0/1")
    value = (
        status.done
        | (status.err << 1)
        | (status.ready << 4)
        | (status.fault << 5)
        | (status.busy << 6)
        | (status.reset_busy << 7)
        | (status.fault_code << 8)
        | (status.last_session << 16)
        | (status.reserved << 24)
    )
    return value


def validate_status(status: Status) -> list[str]:
    errors = []
    if status.reserved != 0:
        errors.append("reserved must be zero")
    if status.ready:
        for name in ("busy", "done", "fault", "reset_busy"):
            if getattr(status, name):
                errors.append(f"READY and {name.upper()} both set")
    if status.fault and status.err == 0:
        errors.append("FAULT requires ERR != 0")
    if status.done and status.err != 0:
        errors.append("successful DONE requires ERR == 0")
    return errors


def decode_control(value: int) -> Control:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("control must be u32")
    return Control(
        soft_reset=(value >> 0) & 1,
        abort_batch=(value >> 1) & 1,
        ack_done=(value >> 2) & 1,
        reserved=(value >> 3) & 0x1FFFFFFF,
    )


def encode_control(control: Control) -> int:
    for name in ("soft_reset", "abort_batch", "ack_done"):
        if getattr(control, name) not in (0, 1):
            raise ValueError(f"{name} must be 0/1")
    if control.reserved != 0:
        raise ValueError("reserved must be zero")
    return (
        control.soft_reset
        | (control.abort_batch << 1)
        | (control.ack_done << 2)
        | (control.reserved << 3)
    )


def ready(status: Status) -> bool:
    return status.ready == 1 and not status.busy and not status.done and not status.fault and not status.reset_busy


def err_name(status: Status) -> str:
    return ERR_NAMES.get(str(status.err), f"UNKNOWN_{status.err}")


def fault_name(status: Status) -> str:
    return FAULT_NAMES.get(str(status.fault_code), f"UNKNOWN_{status.fault_code}")
