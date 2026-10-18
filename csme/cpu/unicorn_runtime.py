"""Optional, synthetic-only x86 runtime for future OpenME ME research.

This module is deliberately an adapter around Unicorn, not an Intel ME
implementation.  It maps deterministic synthetic memory, initializes a small
32-bit x86 register set, and exposes instruction/memory trace events.  It
never opens firmware files and does not provide a loader for proprietary
images.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

try:  # Unicorn is an optional development dependency.
    from unicorn import (
        UC_ARCH_X86,
        UC_HOOK_CODE,
        UC_HOOK_MEM_READ,
        UC_HOOK_MEM_WRITE,
        UC_MEM_READ,
        UC_MODE_32,
        UC_PROT_ALL,
        Uc,
    )
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX
    from unicorn.x86_const import UC_X86_REG_EIP, UC_X86_REG_ESP

    UNICORN_AVAILABLE = True
    UNICORN_IMPORT_ERROR: Optional[Exception] = None
except ImportError as exc:  # pragma: no cover - depends on the environment.
    UNICORN_AVAILABLE = False
    UNICORN_IMPORT_ERROR = exc


class UnicornUnavailableError(RuntimeError):
    """Raised when the optional Unicorn package is not installed."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Page-aligned synthetic memory and deterministic initial registers."""

    code_base: int = 0x1000
    code_size: int = 0x1000
    data_base: int = 0x2000
    data_size: int = 0x1000
    stack_base: int = 0x7000
    stack_size: int = 0x1000
    initial_eip: int = 0x1000
    initial_esp: int = 0x8000
    initial_ebp: int = 0x8000


@dataclass(frozen=True)
class InstructionTrace:
    address: int
    size: int


@dataclass(frozen=True)
class MemoryTrace:
    access: str
    address: int
    size: int
    value: int


TraceListener = Callable[[str, object], None]


class UnicornRuntime:
    """Deterministic 32-bit x86 sandbox for synthetic test instructions.

    The runtime intentionally has no firmware-file or module-loading API.
    Callers provide synthetic instruction bytes with
    :meth:`load_synthetic_code`, then call :meth:`run`.  Trace hooks retain
    instruction and mapped-memory events and may also notify listeners.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        if not UNICORN_AVAILABLE:
            detail = str(UNICORN_IMPORT_ERROR or "package not found")
            raise UnicornUnavailableError(
                "The optional 'unicorn' Python package is required for the "
                f"runtime POC ({detail})."
            )
        self.config = config or RuntimeConfig()
        self.instructions: list[InstructionTrace] = []
        self.memory_accesses: list[MemoryTrace] = []
        self._listeners: list[TraceListener] = []
        self._code_hook = None
        self._memory_hook = None
        self._reset_engine()

    def _reset_engine(self) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        cfg = self.config
        for base, size in (
            (cfg.code_base, cfg.code_size),
            (cfg.data_base, cfg.data_size),
            (cfg.stack_base, cfg.stack_size),
        ):
            self.uc.mem_map(base, size, UC_PROT_ALL)

        self.uc.reg_write(UC_X86_REG_EIP, cfg.initial_eip)
        self.uc.reg_write(UC_X86_REG_ESP, cfg.initial_esp)
        self.uc.reg_write(UC_X86_REG_EBP, cfg.initial_ebp)
        self.uc.reg_write(UC_X86_REG_EAX, 0)
        self.uc.reg_write(UC_X86_REG_EBX, 0)
        self.instructions.clear()
        self.memory_accesses.clear()
        self._code_hook = self.uc.hook_add(UC_HOOK_CODE, self._on_code)
        self._memory_hook = self.uc.hook_add(
            UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._on_memory
        )

    def reset(self) -> None:
        """Reset memory, registers, and traces to the deterministic baseline."""

        self._reset_engine()

    def add_trace_listener(self, listener: TraceListener) -> None:
        """Receive ``("instruction"|"memory", event)`` notifications."""

        self._listeners.append(listener)

    def _notify(self, kind: str, event: object) -> None:
        for listener in tuple(self._listeners):
            listener(kind, event)

    def _on_code(self, _uc, address: int, size: int, _user_data=None) -> None:
        event = InstructionTrace(address, size)
        self.instructions.append(event)
        self._notify("instruction", event)

    def _on_memory(
        self, _uc, access: int, address: int, size: int, value: int, _user_data=None
    ) -> None:
        # Unicorn uses UC_MEM_READ/UC_MEM_WRITE integer constants.  Keeping the
        # public event as text makes traces stable and independent of constants.
        name = "read" if access == UC_MEM_READ else "write"
        event = MemoryTrace(name, address, size, value)
        self.memory_accesses.append(event)
        self._notify("memory", event)

    def load_synthetic_code(self, code: bytes, address: int | None = None) -> int:
        """Write synthetic instruction bytes into the mapped code region.

        This method only accepts bytes supplied by the caller; it does not read
        from a file or interpret a firmware container.
        """

        if not isinstance(code, bytes) or not code:
            raise ValueError("synthetic code must be a non-empty bytes object")
        start = self.config.initial_eip if address is None else address
        end = start + len(code)
        region_end = self.config.code_base + self.config.code_size
        if start < self.config.code_base or end > region_end:
            raise ValueError("synthetic code does not fit in the mapped code region")
        self.uc.mem_write(start, code)
        return start

    def run(self, start: int | None = None, stop: int = 0, count: int = 0) -> None:
        """Run synthetic code with optional Unicorn stop address/instruction count."""

        begin = self.config.initial_eip if start is None else start
        self.uc.emu_start(begin, stop, count=count)

    def registers(self) -> dict[str, int]:
        """Return the small deterministic register set used by this POC."""

        return {
            "eip": self.uc.reg_read(UC_X86_REG_EIP),
            "esp": self.uc.reg_read(UC_X86_REG_ESP),
            "ebp": self.uc.reg_read(UC_X86_REG_EBP),
            "eax": self.uc.reg_read(UC_X86_REG_EAX),
            "ebx": self.uc.reg_read(UC_X86_REG_EBX),
        }

    def read_memory(self, address: int, size: int) -> bytes:
        """Read bytes from the synthetic mapped memory."""

        return bytes(self.uc.mem_read(address, size))


def synthetic_sum_program() -> bytes:
    """Return tiny x86 code that stores and doubles a deterministic value.

    The program is assembled by hand to avoid an assembler dependency:
    ``eax = 0x12345678; [0x2000] = eax; ebx = [0x2000]; eax += ebx; hlt``.
    """

    return bytes(
        (
            0xB8,
            0x78,
            0x56,
            0x34,
            0x12,  # mov eax, 0x12345678
            0xA3,
            0x00,
            0x20,
            0x00,
            0x00,  # mov [0x2000], eax
            0x8B,
            0x1D,
            0x00,
            0x20,
            0x00,
            0x00,  # mov ebx, [0x2000]
            0x01,
            0xD8,  # add eax, ebx
            0xF4,  # hlt
        )
    )
