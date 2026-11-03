"""v3 multi-session Attention codec (DRAFT).

This is intentionally a SEPARATE codec from the frozen v2 contract.py.
It loads contract_v3_session.json, uses 32-byte headers, CRC-32/ISO-HDLC,
session_id at offset 9, and global RESET with session_id=0xFF.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import zlib

_HERE = Path(__file__).resolve().parent
_CONTRACT = json.loads((_HERE / "contract_v3_session.json").read_text(encoding="utf-8"))

MAGIC = int(_CONTRACT["magic_hex"], 16)
PROTOCOL_VERSION = _CONTRACT["protocol_version"]
HEADER_BYTES = _CONTRACT["header_bytes"]
HEADER_LAYOUT = _CONTRACT["header_layout"]
OP_ATTENTION = _CONTRACT["ops"]["attention"]
OP_RESET_CACHE = _CONTRACT["ops"]["reset_cache"]
OP_TEST = _CONTRACT["ops"]["test"]
_OP_NAMES = {number: name for name, number in _CONTRACT["ops"].items()}
_OP_TO_NAME = {v: k for k, v in _CONTRACT["ops"].items()}
CONTROL_SESSION = _CONTRACT["control_session_id"]
MAX_SESSIONS = _CONTRACT["max_sessions"]
SESSION_IDS = tuple(_CONTRACT["session_ids"])
MAX_LAYER = _CONTRACT["layers"] - 1
MAX_T = _CONTRACT["max_t"] - 1
MAX_SEQ = _CONTRACT["sequence_max"]
_HEADER_FMT = "<IHBBBB2sIIH2sI4s"
_CRC_OFFSET = 24
_CRC_SIZE = 4

if HEADER_BYTES != 32 or struct.calcsize(_HEADER_FMT) != HEADER_BYTES:
    raise RuntimeError("v3 header format mismatch")
if [f["field"] for f in HEADER_LAYOUT] != [
    "magic", "version", "op", "flags", "layer", "session_id",
    "padding0", "position", "seq", "payload_len", "padding1", "crc32", "reserved"]:
    raise RuntimeError("v3 header layout differs from codec")


class FrameError(ValueError):
    pass


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _frame_crc(raw_header: bytes, payload: bytes) -> int:
    cleared = raw_header[:_CRC_OFFSET] + bytes(_CRC_SIZE) + raw_header[_CRC_OFFSET + _CRC_SIZE:]
    return crc32(cleared + payload)


@dataclass(frozen=True)
class Header:
    magic: int
    version: int
    op: int
    flags: int
    layer: int
    session_id: int
    position: int
    seq: int
    payload_len: int
    crc32: int


def _pack_header(header: Header) -> bytes:
    return struct.pack(
        _HEADER_FMT, header.magic, header.version, header.op, header.flags,
        header.layer, header.session_id, bytes(2), header.position, header.seq,
        header.payload_len, bytes(2), header.crc32, bytes(4))


def _check_ranges(op, session_id, layer, position, seq):
    if op not in _OP_NAMES:
        raise FrameError(f"unknown op {op}")
    if not 1 <= seq <= MAX_SEQ:
        raise FrameError("seq must be nonzero u32")
    if op == OP_RESET_CACHE:
        if session_id != CONTROL_SESSION:
            raise FrameError("RESET requires session_id=255")
        if layer != 255 or position != 0:
            raise FrameError("RESET requires layer=255 position=0")
        return
    if op in (OP_ATTENTION, OP_TEST):
        if session_id not in SESSION_IDS:
            raise FrameError(f"invalid session_id {session_id}; expected 0..2")
        if not 0 <= layer <= MAX_LAYER:
            raise FrameError("layer out of range")
        if not 0 <= position <= MAX_T:
            raise FrameError("position out of range")
        return
    raise FrameError("op not implemented in v3")


def _expected_payload_bytes(op, direction):
    entry = _CONTRACT["operation_payload_bytes"][_OP_NAMES[op]]
    return entry[direction]


def pack_request(*, seq: int, op: int, layer: int, position: int,
                 session_id: int, payload: bytes) -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        raise FrameError("payload must be bytes")
    payload = bytes(payload)
    _check_ranges(op, session_id, layer, position, seq)
    expected = _expected_payload_bytes(op, "h2c")
    if len(payload) != expected:
        raise FrameError(f"wrong h2c payload length: {len(payload)} != {expected}")
    header = Header(MAGIC, PROTOCOL_VERSION, op, 0, layer, session_id,
                    position, seq, len(payload), 0)
    raw = _pack_header(header)
    crc = _frame_crc(raw, payload)
    return _pack_header(
        Header(MAGIC, PROTOCOL_VERSION, op, 0, layer, session_id, position, seq, len(payload), crc)
    ) + payload


def pack_response(*, seq: int, op: int, layer: int, position: int,
                  session_id: int, payload: bytes) -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        raise FrameError("payload must be bytes")
    payload = bytes(payload)
    _check_ranges(op, session_id, layer, position, seq)
    expected = _expected_payload_bytes(op, "c2h")
    if len(payload) != expected:
        raise FrameError(f"wrong c2h payload length: {len(payload)} != {expected}")
    header = Header(MAGIC, PROTOCOL_VERSION, op, 0, layer, session_id,
                    position, seq, len(payload), 0)
    raw = _pack_header(header)
    crc = _frame_crc(raw, payload)
    return _pack_header(
        Header(MAGIC, PROTOCOL_VERSION, op, 0, layer, session_id, position, seq, len(payload), crc)
    ) + payload


def unpack_header(raw: bytes, *, direction: str) -> Header:
    if not isinstance(raw, bytes) or len(raw) != HEADER_BYTES:
        raise FrameError("header must be 32 bytes")
    fields = struct.unpack(_HEADER_FMT, raw)
    if fields[6] != bytes(2) or fields[10] != bytes(2) or fields[12] != bytes(4):
        raise FrameError("nonzero padding/reserved")
    header = Header(fields[0], fields[1], fields[2], fields[3], fields[4],
                    fields[5], fields[7], fields[8], fields[9], fields[11])
    if header.magic != MAGIC:
        raise FrameError("bad magic")
    if header.version != PROTOCOL_VERSION:
        raise FrameError("bad version; v2 and unknown versions rejected")
    if header.flags != 0:
        raise FrameError("flags must be zero")
    _check_ranges(header.op, header.session_id, header.layer, header.position, header.seq)
    expected = _expected_payload_bytes(header.op, direction)
    if header.payload_len != expected:
        raise FrameError(f"wrong payload_len {header.payload_len} != {expected}")
    return header


def unpack_frame(raw: bytes, *, direction: str):
    if not isinstance(raw, bytes) or len(raw) < HEADER_BYTES:
        raise FrameError("short frame")
    header = unpack_header(raw[:HEADER_BYTES], direction=direction)
    payload = raw[HEADER_BYTES:]
    if len(payload) != header.payload_len:
        raise FrameError("frame length does not match payload_len")
    if _frame_crc(raw[:HEADER_BYTES], payload) != header.crc32:
        raise FrameError("bad CRC")
    return header, payload


def check_response(request: Header, raw_response: bytes) -> bytes:
    response, payload = unpack_frame(raw_response, direction="c2h")
    for field in ("op", "seq", "session_id", "layer", "position"):
        if getattr(response, field) != getattr(request, field):
            raise FrameError(f"response {field} mismatch")
    if response.crc32 != _frame_crc(raw_response[:HEADER_BYTES], payload):
        raise FrameError("bad response CRC")
    return payload
