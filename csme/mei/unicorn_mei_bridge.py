"""Synthetic Unicorn-to-MEI bridge for deterministic OpenME experiments.

This module connects the optional Unicorn CPU sandbox to the project-defined
MEI/HBM transport model.  It uses a small synthetic mailbox and doorbell in
the mapped data region; it does not load firmware, emulate Intel identifiers,
or access hardware.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .mei_hbm import Completion, Interrupt, MEIHBMModel, MessageTooLargeError
from ..cpu.unicorn_runtime import UnicornRuntime


REQUEST_BASE = 0x2100
RESPONSE_BASE = 0x2200
DOORBELL_ADDRESS = 0x2FF0
REQUEST_HEADER_SIZE = 8
RESPONSE_HEADER_SIZE = 12


class BridgeError(ValueError):
    """Raised when a synthetic bridge transaction is malformed."""


@dataclass(frozen=True)
class BridgeResult:
    """Completion and deterministic bridge trace for one transaction."""

    completion: Completion
    events: tuple[str, ...]


def synthetic_doorbell_program() -> bytes:
    """Return code that copies a mailbox opcode to the synthetic doorbell."""

    return bytes(
        (
            0xA1,
            0x00,
            0x21,
            0x00,
            0x00,  # mov eax, [0x2100]
            0xA3,
            0xF0,
            0x2F,
            0x00,
            0x00,  # mov [0x2ff0], eax
            0x8B,
            0x1D,
            0x00,
            0x22,
            0x00,
            0x00,  # mov ebx, [0x2200]
            0xF4,  # hlt
        )
    )


class UnicornMEIBridge:
    """Run one synthetic CPU mailbox transaction through the MEI model."""

    def __init__(
        self,
        runtime: UnicornRuntime | None = None,
        model: MEIHBMModel | None = None,
    ) -> None:
        self.runtime = runtime or UnicornRuntime()
        self.model = model or MEIHBMModel()
        self.events: list[str] = []
        self._completion: Completion | None = None
        self.runtime.add_trace_listener(self._on_trace)
        self._prepare_transport()

    def _prepare_transport(self) -> None:
        self.model.reset()
        self.model.set_ready()

    def _on_trace(self, kind: str, event: object) -> None:
        if kind != "memory" or getattr(event, "access", None) != "write":
            return
        if getattr(event, "address", None) != DOORBELL_ADDRESS:
            return

        opcode = int(event.value)
        header = self.runtime.read_memory(REQUEST_BASE, REQUEST_HEADER_SIZE)
        requested_opcode, payload_length = struct.unpack("<II", header)
        if requested_opcode != opcode:
            raise BridgeError("doorbell opcode does not match mailbox opcode")
        payload = self.runtime.read_memory(
            REQUEST_BASE + REQUEST_HEADER_SIZE, payload_length
        )
        sequence = self.model.host_submit(opcode, payload)
        self.events.append(f"host_submit:{sequence}:{opcode}")
        self.model.me_service(limit=1)
        completion = self.model.host_poll_completion()
        self._completion = completion
        response = struct.pack(
            "<III", completion.sequence, completion.opcode, completion.status
        ) + completion.payload
        self.runtime.uc.mem_write(RESPONSE_BASE, response)
        self.events.append(f"me_complete:{completion.sequence}:{completion.status}")
        self.model.ack_interrupts(Interrupt.ME_INPUT | Interrupt.HOST_INPUT)
        self.events.append("interrupts_acknowledged")

    def submit(self, opcode: int, payload: bytes = b"") -> BridgeResult:
        """Run a bounded synthetic request and return its MEI completion."""

        if not isinstance(opcode, int) or opcode < 0:
            raise BridgeError("opcode must be a non-negative integer")
        payload = bytes(payload)
        if len(payload) > self.model.max_payload:
            raise MessageTooLargeError(
                f"payload length {len(payload)} exceeds {self.model.max_payload}"
            )

        self.runtime.reset()
        self._prepare_transport()
        self.events = ["reset"]
        self._completion = None
        mailbox = struct.pack("<II", opcode, len(payload)) + payload
        self.runtime.uc.mem_write(REQUEST_BASE, mailbox)
        self.runtime.load_synthetic_code(synthetic_doorbell_program())
        self.runtime.run()
        if self._completion is None:
            raise BridgeError("synthetic program did not ring the doorbell")
        return BridgeResult(self._completion, tuple(self.events))

    def response_bytes(self) -> bytes:
        """Read the last synthetic completion mailbox."""

        if self._completion is None:
            raise BridgeError("no transaction has completed")
        return self.runtime.read_memory(
            RESPONSE_BASE,
            RESPONSE_HEADER_SIZE + len(self._completion.payload),
        )


__all__ = [
    "BridgeError",
    "BridgeResult",
    "DOORBELL_ADDRESS",
    "REQUEST_BASE",
    "RESPONSE_BASE",
    "UnicornMEIBridge",
    "synthetic_doorbell_program",
]
