"""Testable PCI/MMIO façade for the OpenME fake-ME model.

This module defines the contract a future native QEMU device will implement.
It is intentionally not wired to Intel PCI identifiers or the Linux MEI
driver, and it performs no DMA or hardware access.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .fake_me import FakeME, Request, Response, State

# Project-defined emulation identifiers. These must not impersonate Intel.
PCI_VENDOR_ID_OPENME_TEST = 0x1234
PCI_DEVICE_ID_OPENME_TEST = 0x4D45

REG_STATUS = 0x00
REG_CONTROL = 0x04
REG_VERSION = 0x08
REG_EVENT = 0x0C
REG_RX_LENGTH = 0x10
REG_DOORBELL = 0x14

STATUS_READY = 1 << 0
STATUS_IRQ_PENDING = 1 << 1
STATUS_SUSPENDED = 1 << 2

CONTROL_RESET = 1 << 0
CONTROL_ACK_IRQ = 1 << 1

COMMANDS = {
    1: "RESET",
    2: "START",
    3: "ENUMERATE",
    4: "PROPERTIES",
    5: "CONNECT",
    6: "FLOW_CONTROL",
    7: "DISCONNECT",
    8: "SUSPEND",
    9: "RESUME",
}


@dataclass
class OpenMEPCIShell:
    """A bounded MMIO/register façade around :class:`FakeME`."""

    model: FakeME = field(default_factory=FakeME)
    response_queue: deque[Response] = field(default_factory=lambda: deque(maxlen=8))
    irq_pending: bool = False

    def _status(self) -> int:
        value = 0
        if self.model.state != State.RESET:
            value |= STATUS_READY
        if self.irq_pending:
            value |= STATUS_IRQ_PENDING
        if self.model.state == State.SUSPENDED:
            value |= STATUS_SUSPENDED
        return value

    def read(self, offset: int) -> int:
        if offset == REG_STATUS:
            return self._status()
        if offset == REG_VERSION:
            return 0x00010000
        if offset == REG_EVENT:
            return self.model.event
        if offset == REG_RX_LENGTH:
            return len(self.response_queue[0].payload) if self.response_queue else 0
        raise ValueError(f"unsupported MMIO read offset 0x{offset:02x}")

    def write(self, offset: int, value: int) -> None:
        if offset == REG_CONTROL:
            if value & CONTROL_RESET:
                self.response_queue.clear()
                self.irq_pending = False
                self.model.handle(Request("RESET"))
            if value & CONTROL_ACK_IRQ:
                self.irq_pending = bool(self.response_queue)
            return
        if offset == REG_DOORBELL:
            command = COMMANDS.get(value)
            if command is None:
                raise ValueError(f"unsupported doorbell command {value}")
            self.submit(Request(command))
            return
        raise ValueError(f"unsupported MMIO write offset 0x{offset:02x}")

    def submit(self, request: Request) -> None:
        if len(self.response_queue) >= self.response_queue.maxlen:
            raise BufferError("response queue is full")
        self.response_queue.append(self.model.handle(request))
        self.irq_pending = True

    def pop_response(self) -> Response:
        if not self.response_queue:
            raise BufferError("response queue is empty")
        response = self.response_queue.popleft()
        self.irq_pending = bool(self.response_queue)
        return response

