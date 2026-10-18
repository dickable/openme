"""Deterministic, synthetic host-side MEI/HBM transport model.

This module models only the host-facing transport concepts described by the
public Linux MEI documentation: host/ME readiness, reset, circular message
buffers, interrupts, and completion delivery.  It is not an Intel ME
implementation and does not consume firmware or model undocumented hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntFlag
from typing import Generic, Iterable, Optional, TypeVar


class MEIError(Exception):
    """Base class for deterministic model errors."""


class NotReadyError(MEIError):
    """Raised when traffic is attempted before both sides are ready."""


class BufferFullError(MEIError):
    """Raised when a circular buffer has no free slot."""


class MessageTooLargeError(MEIError):
    """Raised when a payload cannot fit in one synthetic message slot."""


class SideState(Enum):
    RESET = "reset"
    READY = "ready"


class Interrupt(IntFlag):
    """Synthetic interrupt causes, named from the perspective of the peer."""

    NONE = 0
    ME_INPUT = 1       # host placed a message in the host->ME buffer
    HOST_INPUT = 2     # ME placed a completion in the ME->host buffer


@dataclass(frozen=True)
class HostMessage:
    """One bounded message placed in the host-to-ME circular buffer."""

    sequence: int
    opcode: int
    payload: bytes


@dataclass(frozen=True)
class Completion:
    """Completion produced after the synthetic ME services a message."""

    sequence: int
    opcode: int
    status: int
    payload: bytes


T = TypeVar("T")


class CircularBuffer(Generic[T]):
    """Fixed-slot FIFO with deterministic wrap-around behavior."""

    def __init__(self, slot_count: int) -> None:
        if slot_count < 1:
            raise ValueError("slot_count must be positive")
        self._slots: list[Optional[T]] = [None] * slot_count
        self._read_index = 0
        self._write_index = 0
        self._count = 0

    @property
    def capacity(self) -> int:
        return len(self._slots)

    @property
    def count(self) -> int:
        return self._count

    @property
    def free(self) -> int:
        return self.capacity - self._count

    @property
    def empty(self) -> bool:
        return self._count == 0

    @property
    def full(self) -> bool:
        return self._count == self.capacity

    @property
    def read_index(self) -> int:
        return self._read_index

    @property
    def write_index(self) -> int:
        return self._write_index

    def push(self, item: T) -> None:
        if self.full:
            raise BufferFullError("circular buffer is full")
        self._slots[self._write_index] = item
        self._write_index = (self._write_index + 1) % self.capacity
        self._count += 1

    def pop(self) -> T:
        if self.empty:
            raise IndexError("circular buffer is empty")
        item = self._slots[self._read_index]
        self._slots[self._read_index] = None
        self._read_index = (self._read_index + 1) % self.capacity
        self._count -= 1
        assert item is not None
        return item

    def clear(self) -> None:
        self._slots = [None] * self.capacity
        self._read_index = 0
        self._write_index = 0
        self._count = 0


@dataclass(frozen=True)
class ServiceReport:
    """Result of one ME service pass."""

    processed: int
    blocked_by_output_capacity: bool


class MEIHBMModel:
    """A small, deterministic model of the host-facing HBM transport.

    The model intentionally gives the ME a trivial service behavior: every
    accepted request produces a successful completion that echoes its payload.
    This is useful for transport tests, but it is not a claim about Intel ME
    services or a substitute for a real ME firmware implementation.
    """

    def __init__(
        self,
        *,
        slot_count: int = 4,
        slot_size: int = 64,
        header_size: int = 8,
    ) -> None:
        if slot_size <= header_size:
            raise ValueError("slot_size must be larger than header_size")
        if header_size < 0:
            raise ValueError("header_size must not be negative")
        self.slot_size = slot_size
        self.header_size = header_size
        self.max_payload = slot_size - header_size
        self._host_to_me = CircularBuffer[HostMessage](slot_count)
        self._me_to_host = CircularBuffer[Completion](slot_count)
        self._next_sequence = 0
        self._interrupts = Interrupt.NONE
        self.host_state = SideState.RESET
        self.me_state = SideState.RESET

    @property
    def ready(self) -> bool:
        return (
            self.host_state is SideState.READY
            and self.me_state is SideState.READY
        )

    @property
    def interrupts(self) -> Interrupt:
        return self._interrupts

    @property
    def host_to_me_count(self) -> int:
        return self._host_to_me.count

    @property
    def me_to_host_count(self) -> int:
        return self._me_to_host.count

    @property
    def host_to_me_indices(self) -> tuple[int, int]:
        return self._host_to_me.read_index, self._host_to_me.write_index

    @property
    def me_to_host_indices(self) -> tuple[int, int]:
        return self._me_to_host.read_index, self._me_to_host.write_index

    def reset(self) -> None:
        """Assert a shared reset and return all transport state to baseline."""

        self.host_state = SideState.RESET
        self.me_state = SideState.RESET
        self._host_to_me.clear()
        self._me_to_host.clear()
        self._next_sequence = 0
        self._interrupts = Interrupt.NONE

    def set_host_ready(self) -> None:
        self.host_state = SideState.READY

    def set_me_ready(self) -> None:
        self.me_state = SideState.READY

    def set_ready(self) -> None:
        """Convenience handshake for deterministic tests."""

        self.set_host_ready()
        self.set_me_ready()

    def ack_interrupts(self, mask: Interrupt) -> None:
        self._interrupts &= ~mask

    def host_submit(self, opcode: int, payload: bytes = b"") -> int:
        """Place one request in the host-to-ME ring and return its sequence."""

        self._require_ready()
        payload = bytes(payload)
        self._check_payload(payload)
        sequence = self._next_sequence
        self._next_sequence += 1
        self._host_to_me.push(HostMessage(sequence, int(opcode), payload))
        self._interrupts |= Interrupt.ME_INPUT
        return sequence

    def me_service(self, limit: Optional[int] = None) -> ServiceReport:
        """Consume requests and queue successful synthetic completions.

        If the output ring is full, the input request remains queued.  This
        makes backpressure observable and prevents silent message loss.
        """

        self._require_ready()
        if limit is not None and limit < 0:
            raise ValueError("limit must not be negative")
        processed = 0
        blocked = False
        while not self._host_to_me.empty and (
            limit is None or processed < limit
        ):
            if self._me_to_host.full:
                blocked = True
                break
            request = self._host_to_me.pop()
            self._me_to_host.push(
                Completion(
                    sequence=request.sequence,
                    opcode=request.opcode,
                    status=0,
                    payload=request.payload,
                )
            )
            processed += 1
        if self._host_to_me.empty:
            self._interrupts &= ~Interrupt.ME_INPUT
        if processed:
            self._interrupts |= Interrupt.HOST_INPUT
        return ServiceReport(processed, blocked)

    def host_poll_completion(self) -> Completion:
        """Pop one completion from the ME-to-host ring."""

        self._require_ready()
        completion = self._me_to_host.pop()
        if self._me_to_host.empty:
            # The interrupt remains latched until explicitly acknowledged.
            pass
        return completion

    def pending_requests(self) -> tuple[HostMessage, ...]:
        """Return a non-mutating snapshot in logical FIFO order."""

        return self._snapshot(self._host_to_me)

    def pending_completions(self) -> tuple[Completion, ...]:
        """Return a non-mutating snapshot in logical FIFO order."""

        return self._snapshot(self._me_to_host)

    def _require_ready(self) -> None:
        if not self.ready:
            raise NotReadyError("both host and ME must be ready")

    def _check_payload(self, payload: bytes) -> None:
        if len(payload) > self.max_payload:
            raise MessageTooLargeError(
                f"payload length {len(payload)} exceeds {self.max_payload}"
            )

    @staticmethod
    def _snapshot(buffer: CircularBuffer[T]) -> tuple[T, ...]:
        items: list[T] = []
        index = buffer.read_index
        for _ in range(buffer.count):
            item = buffer._slots[index]
            assert item is not None
            items.append(item)
            index = (index + 1) % buffer.capacity
        return tuple(items)


__all__ = [
    "BufferFullError",
    "CircularBuffer",
    "Completion",
    "HostMessage",
    "Interrupt",
    "MEIError",
    "MEIHBMModel",
    "MessageTooLargeError",
    "NotReadyError",
    "ServiceReport",
    "SideState",
]
