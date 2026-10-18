"""Project-defined bounded frame transport for the deterministic fake ME model.

This is an OpenME test protocol, not Intel HECI/MEI.  It provides a strict
wire-format adapter around ``FakeME`` so software tests can record, replay,
and compare complete request/response frames without hardware or firmware.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

from .fake_me import FakeME, Request


MAGIC = 0x4F4D
VERSION = 1
HEADER_SIZE = 16
MAX_PAYLOAD = 256
MAX_FRAME = HEADER_SIZE + MAX_PAYLOAD
QUEUE_CAPACITY = 8
REQUEST_FLAGS = 0
RESPONSE_FLAG = 0x01
ERROR_FLAG = 0x02
HEADER_FORMAT = "<HBBBBHIHH"


class Opcode(IntEnum):
    RESET = 0x01
    START = 0x02
    ENUMERATE = 0x03
    PROPERTIES = 0x04
    CONNECT = 0x05
    FLOW_CONTROL = 0x06
    DATA = 0x07
    DISCONNECT = 0x08
    SUSPEND = 0x09
    RESUME = 0x0A


class Status(IntEnum):
    OK = 0x00
    BAD_MAGIC = 0x01
    BAD_VERSION = 0x02
    BAD_FLAGS = 0x03
    BAD_LENGTH = 0x04
    UNKNOWN_OPCODE = 0x05
    NOT_READY = 0x06
    INVALID_STATE = 0x07
    UNKNOWN_CLIENT = 0x08
    MESSAGE_TOO_LARGE = 0x09
    QUEUE_FULL = 0x0A
    MALFORMED_PAYLOAD = 0x0B
    UNSUPPORTED = 0x0C


COMMAND_NAMES = {opcode.value: opcode.name for opcode in Opcode}
STATUS_BY_MODEL_RESULT = {
    "ok": Status.OK,
    "unsupported-command": Status.UNKNOWN_OPCODE,
    "unsupported-version": Status.BAD_VERSION,
    "invalid-state": Status.INVALID_STATE,
    "unsupported-client": Status.UNKNOWN_CLIENT,
    "message-too-large": Status.MESSAGE_TOO_LARGE,
    "unsupported": Status.UNSUPPORTED,
}


@dataclass(frozen=True)
class Frame:
    """One complete v0 wire frame."""

    opcode: int
    sequence: int
    payload: bytes = b""
    version: int = VERSION
    flags: int = REQUEST_FLAGS
    status: int = Status.OK

    def encode(self) -> bytes:
        if not 1 <= self.sequence <= 0xFFFFFFFF:
            raise ValueError("sequence must be non-zero and fit in uint32")
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError("payload exceeds the v0 maximum")
        if not 0 <= self.opcode <= 0xFF:
            raise ValueError("opcode must fit in uint8")
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC,
            self.version,
            self.flags,
            self.opcode,
            self.status,
            0,
            self.sequence,
            len(self.payload),
            0,
        )
        return header + self.payload


class FrameError(ValueError):
    """A rejected frame with a protocol status suitable for diagnostics."""

    def __init__(self, status: Status, message: str):
        super().__init__(message)
        self.status = status


def decode_frame(data: bytes, *, require_request: bool = False) -> Frame:
    """Decode one exact-length frame and reject malformed fields."""

    if len(data) < HEADER_SIZE:
        raise FrameError(Status.BAD_LENGTH, "frame is shorter than the header")
    magic, version, flags, opcode, status, reserved_a, sequence, payload_len, reserved_b = (
        struct.unpack_from(HEADER_FORMAT, data)
    )
    if magic != MAGIC:
        raise FrameError(Status.BAD_MAGIC, "frame magic is invalid")
    if version != VERSION:
        raise FrameError(Status.BAD_VERSION, "frame version is unsupported")
    if require_request and flags != REQUEST_FLAGS:
        raise FrameError(Status.BAD_FLAGS, "request flags must be zero")
    if reserved_a or reserved_b:
        raise FrameError(Status.BAD_LENGTH, "reserved fields must be zero")
    if sequence == 0:
        raise FrameError(Status.BAD_LENGTH, "sequence must be non-zero")
    if payload_len > MAX_PAYLOAD:
        raise FrameError(Status.MESSAGE_TOO_LARGE, "declared payload exceeds the v0 maximum")
    if len(data) != HEADER_SIZE + payload_len:
        raise FrameError(Status.BAD_LENGTH, "declared payload length does not match frame")
    return Frame(
        opcode=opcode,
        sequence=sequence,
        payload=data[HEADER_SIZE:],
        version=version,
        flags=flags,
        status=status,
    )


def error_response(data: bytes, status: Status) -> bytes:
    """Build an error response for a complete or partially valid request."""

    opcode = data[4] if len(data) >= 5 else 0
    sequence = struct.unpack_from("<I", data, 8)[0] if len(data) >= 12 else 1
    if sequence == 0:
        sequence = 1
    return Frame(
        opcode=opcode,
        sequence=sequence,
        flags=RESPONSE_FLAG | ERROR_FLAG,
        status=status,
    ).encode()


@dataclass
class FramedTransport:
    """A deterministic frame adapter around :class:`FakeME`."""

    model: FakeME

    def __init__(self, model: FakeME | None = None):
        self.model = model or FakeME()

    def handle(self, data: bytes, *, client: str = "") -> bytes:
        try:
            request = decode_frame(data, require_request=True)
        except FrameError as exc:
            if len(data) < HEADER_SIZE:
                raise
            return error_response(data, exc.status)

        command = COMMAND_NAMES.get(request.opcode)
        if command is None:
            return self._response(request, Status.UNKNOWN_OPCODE)

        response = self.model.handle(Request(
            command,
            client=client,
            payload=request.payload,
            version=request.version,
        ))
        status = STATUS_BY_MODEL_RESULT.get(response.status, Status.UNSUPPORTED)
        return self._response(request, status, response.payload)

    @staticmethod
    def _response(request: Frame, status: Status, payload: bytes = b"") -> bytes:
        flags = RESPONSE_FLAG | (ERROR_FLAG if status != Status.OK else 0)
        if status != Status.OK:
            payload = b""
        return Frame(
            opcode=request.opcode,
            sequence=request.sequence,
            payload=payload,
            flags=flags,
            status=status,
        ).encode()


@dataclass
class QueuedFramedTransport:
    """Bounded submit/service/pop adapter for host-side testing.

    This implements the OpenME test contract's explicit service steps. It is
    not an Intel HECI/MEI implementation and does not load firmware.
    """

    model: FakeME
    capacity: int = QUEUE_CAPACITY
    request_queue: list[tuple[bytes, str]] = field(default_factory=list)
    response_queue: list[bytes] = field(default_factory=list)
    reserved_responses: int = 0
    overflow_count: int = 0
    last_submit_status: Status = Status.OK

    def __init__(self, model: FakeME | None = None, capacity: int = QUEUE_CAPACITY):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.model = model or FakeME()
        self.capacity = capacity
        self.request_queue = []
        self.response_queue = []
        self.reserved_responses = 0
        self.overflow_count = 0
        self.last_submit_status = Status.OK

    def _reject(self, status: Status) -> Status:
        self.last_submit_status = status
        if status == Status.QUEUE_FULL and self.overflow_count < 0xFFFFFFFF:
            self.overflow_count += 1
        return status

    def submit(self, data: bytes, *, client: str = "") -> Status:
        """Accept one complete-enough frame or reject it atomically."""

        if len(data) < HEADER_SIZE:
            return self._reject(Status.BAD_LENGTH)
        try:
            payload_len = struct.unpack_from("<H", data, 12)[0]
        except struct.error:
            return self._reject(Status.BAD_LENGTH)
        declared_length = HEADER_SIZE + payload_len
        if len(data) < declared_length:
            return self._reject(Status.BAD_LENGTH)
        if (len(self.request_queue) >= self.capacity or
                len(self.response_queue) + self.reserved_responses >= self.capacity):
            return self._reject(Status.QUEUE_FULL)
        self.request_queue.append((bytes(data), client))
        self.reserved_responses += 1
        self.last_submit_status = Status.OK
        return Status.OK

    def service(self) -> bytes | None:
        """Process one queued request and append exactly one response."""

        if not self.request_queue:
            return None
        data, client = self.request_queue.pop(0)
        self.reserved_responses -= 1
        try:
            request = decode_frame(data, require_request=True)
        except FrameError as exc:
            response = error_response(data, exc.status)
        else:
            command = COMMAND_NAMES.get(request.opcode)
            if command is None:
                response = FramedTransport._response(request, Status.UNKNOWN_OPCODE)
            else:
                model_response = self.model.handle(Request(
                    command,
                    client=client,
                    payload=request.payload,
                    version=request.version,
                ))
                status = STATUS_BY_MODEL_RESULT.get(model_response.status, Status.UNSUPPORTED)
                response = FramedTransport._response(request, status, model_response.payload)

        # An in-band reset isolates the reset response from earlier work and
        # drops requests that were queued behind it.
        try:
            is_reset = decode_frame(data, require_request=False).opcode == Opcode.RESET
        except FrameError:
            is_reset = False
        if is_reset:
            self.request_queue.clear()
            self.response_queue.clear()
            self.reserved_responses = 0
        self.response_queue.append(response)
        return response

    def pop_response(self) -> bytes | None:
        """Remove and return the oldest response frame, if any."""

        if not self.response_queue:
            return None
        return self.response_queue.pop(0)
