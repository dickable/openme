"""Real-byte execution backend used only after the image-specific gates pass.

This backend is intentionally strict. It can execute bytes copied from a
bounded, uncompressed CPD range with Unicorn's x86-32 engine, but it refuses
to invent an entry point, decompress a module with an unverified algorithm, or
replace the missing ME ROM/library environment with a synthetic success path.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from unicorn import (
        UC_ARCH_X86,
        UC_HOOK_CODE,
        UC_HOOK_MEM_READ,
        UC_HOOK_MEM_WRITE,
        UC_HOOK_MEM_INVALID,
        UC_MEM_READ,
        UC_MEM_WRITE,
        UC_MEM_READ_UNMAPPED,
        UC_MEM_WRITE_UNMAPPED,
        UC_MEM_FETCH_UNMAPPED,
        UC_MODE_32,
        UC_PROT_EXEC,
        UC_PROT_READ,
        UC_PROT_WRITE,
        Uc,
    )
    from unicorn.x86_const import (
        UC_X86_REG_EAX,
        UC_X86_REG_EBP,
        UC_X86_REG_EBX,
        UC_X86_REG_ECX,
        UC_X86_REG_EDI,
        UC_X86_REG_EDX,
        UC_X86_REG_ESI,
        UC_X86_REG_ESP,
        UC_X86_REG_EIP,
        UC_X86_REG_EFLAGS,
    )

    UNICORN_AVAILABLE = True
    UNICORN_IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # pragma: no cover - environment dependent
    UNICORN_AVAILABLE = False
    UNICORN_IMPORT_ERROR = exc

from .module_loader import LoadedModule
from .host_platform import MEI_BASE, PCH_BASE, PCH_SIZE, RealImageHostPlatform, SPI_BASE


PAGE = 0x1000


def align_down(value: int) -> int:
    return value & ~(PAGE - 1)


def align_up(value: int) -> int:
    return (value + PAGE - 1) & ~(PAGE - 1)


@dataclass(frozen=True)
class RealRuntimeConfig:
    max_instructions: int = 100_000
    timeout_seconds: float = 10.0
    sram_base: int = 0x00100000
    sram_size: int = 0x00080000
    dram_base: int = 0x00200000
    dram_size: int = 0x00200000
    stack_base: int = 0x003FE000
    stack_size: int = 0x00001000
    stack_top: int = 0x003FF000
    module_heap_base: int | None = None
    module_heap_size: int = 0
    module_bss_base: int | None = None
    module_bss_size: int = 0
    evidence_global_base: int | None = None
    evidence_global_size: int = 0
    pch_base: int = 0x20000000
    pch_size: int = 0x10000
    mei_base: int = 0x20010000
    mei_size: int = 0x1000
    spi_base: int = SPI_BASE


class RealRuntimeStop(RuntimeError):
    """Controlled stop raised by the real-byte execution hooks."""


class RealUnicornRuntime:
    """A bounded x86-32 runtime for a verified real module range."""

    def __init__(
        self,
        image: bytes,
        image_sha256: str,
        trace_path: Path,
        config: RealRuntimeConfig | None = None,
    ) -> None:
        if not UNICORN_AVAILABLE:
            raise RealRuntimeStop(
                "Unicorn is unavailable: " + str(UNICORN_IMPORT_ERROR or "not installed")
            )
        self.image = image
        self.image_sha256 = image_sha256
        self.trace_path = Path(trace_path)
        self.config = config or RealRuntimeConfig()
        self.instructions = 0
        self.bytes_executed = 0
        self.memory_accesses = 0
        self.stop_reason: str | None = None
        self._started_at = 0.0
        self._trace_file = None
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.host = RealImageHostPlatform(image)
        self._code_base = 0
        self._valid_code_end = 0
        self._last_instruction: dict[str, Any] | None = None

    def _emit(self, event: dict[str, Any]) -> None:
        if self._trace_file is not None:
            self._trace_file.write(json.dumps(event, sort_keys=True) + "\n")
            self._trace_file.flush()

    def _on_code(self, _uc: Any, address: int, size: int, _user: Any = None) -> None:
        self.instructions += 1
        self.bytes_executed += size
        self._sync_host_memory()
        instruction_bytes = bytes(self.uc.mem_read(address, size)).hex()
        self._last_instruction = {
            "address": f"0x{address:x}",
            "size": size,
            "bytes": instruction_bytes,
            "sequence": self.instructions,
        }
        if address < self._code_base or address + size > self._valid_code_end:
            raise RealRuntimeStop(
                f"instruction fetch outside valid module extent at 0x{address:x} "
                f"(valid 0x{self._code_base:x}-0x{self._valid_code_end:x})"
            )
        self._emit(
            {
                "type": "instruction",
                "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                "address": f"0x{address:x}",
                "size": size,
                "bytes": instruction_bytes,
                "image_sha256": self.image_sha256,
                "sequence": self.instructions,
            }
        )
        if self.instructions >= self.config.max_instructions:
            raise RealRuntimeStop("instruction timeout budget exhausted")
        if time.monotonic() - self._started_at > self.config.timeout_seconds:
            raise RealRuntimeStop("wall-clock timeout")

    def _on_memory(
        self,
        _uc: Any,
        access: int,
        address: int,
        size: int,
        value: int,
        _user: Any = None,
    ) -> None:
        self.memory_accesses += 1
        kind = "read" if access == UC_MEM_READ else "write"
        is_spi = self.config.spi_base <= address < self.config.spi_base + len(self.image)
        is_pch = self.config.pch_base <= address < self.config.pch_base + self.config.pch_size
        is_mei = self.config.mei_base <= address < self.config.mei_base + self.config.mei_size
        domain = "SPI" if is_spi else "MMIO" if is_pch or is_mei else "memory"
        self._emit(
            {
                "type": "spi" if domain == "SPI" else "mmio" if domain == "MMIO" else "memory",
                "domain": domain,
                "access": kind,
                "address": f"0x{address:x}",
                "size": size,
                "value": value,
                "image_sha256": self.image_sha256,
                "sequence": self.memory_accesses,
            }
        )
        if is_spi and kind == "write":
            raise RealRuntimeStop("write to preserved SPI image denied")
        if is_pch or is_mei:
            if kind == "write" and not self.host.write(address, size, value):
                raise RealRuntimeStop(f"unsupported host-model write at 0x{address:x}")
            self._sync_host_memory()

    def _on_invalid(
        self,
        _uc: Any,
        access: int,
        address: int,
        size: int,
        value: int,
        _user: Any = None,
    ) -> bool:
        kind = (
            "read"
            if access in (UC_MEM_READ, UC_MEM_READ_UNMAPPED)
            else "write"
            if access in (UC_MEM_WRITE, UC_MEM_WRITE_UNMAPPED)
            else "fetch"
        )
        registers = self._register_dump()
        self._emit(
            {
                "type": "invalid-memory",
                "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                "access": kind,
                "address": f"0x{address:x}",
                "size": size,
                "value": value,
                "image_sha256": self.image_sha256,
                "sequence": self.memory_accesses + 1,
                "instruction": self._last_instruction,
                "registers": registers,
            }
        )
        raise RealRuntimeStop(f"invalid {kind} at 0x{address:x} size={size} value=0x{value:x}")

    def run(self, module: LoadedModule, entry_offset: int) -> dict[str, Any]:
        """Execute only the selected real module bytes; never synthesize code."""

        valid_extent = len(module.data) if module.valid_extent is None else module.valid_extent
        if valid_extent <= 0 or valid_extent > len(module.data):
            raise RealRuntimeStop("module valid extent is outside decoded module capacity")
        if entry_offset < 0 or entry_offset >= valid_extent:
            raise RealRuntimeStop("entry point is outside the bounded module")

        code_base = align_down(module.candidate.guest_base)
        code_end = align_up(module.candidate.guest_base + len(module.data))
        entry = module.candidate.guest_base + entry_offset
        self._code_base = module.candidate.guest_base
        self._valid_code_end = module.candidate.guest_base + valid_extent
        self.uc.mem_map(code_base, code_end - code_base, UC_PROT_READ | UC_PROT_EXEC)
        self.uc.mem_write(module.candidate.guest_base, module.data)
        spi_size = align_up(len(self.image))
        self.uc.mem_map(self.config.spi_base, spi_size, UC_PROT_READ)
        self.uc.mem_write(self.config.spi_base, self.image)
        self.uc.mem_map(self.config.sram_base, self.config.sram_size, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_map(self.config.dram_base, self.config.dram_size, UC_PROT_READ | UC_PROT_WRITE)
        writable_ranges = [
            (self.config.sram_base, self.config.sram_base + self.config.sram_size),
            (self.config.dram_base, self.config.dram_base + self.config.dram_size),
        ]

        def map_writable_region(base: int, size: int) -> None:
            if not size:
                return
            start = align_down(base)
            end = align_up(base + size)
            if any(start >= left and end <= right for left, right in writable_ranges):
                return
            self.uc.mem_map(start, end - start, UC_PROT_READ | UC_PROT_WRITE)
            writable_ranges.append((start, end))

        map_writable_region(self.config.stack_base, self.config.stack_size)
        if self.config.module_heap_base is not None:
            map_writable_region(self.config.module_heap_base, self.config.module_heap_size)
        if self.config.module_bss_base is not None:
            map_writable_region(self.config.module_bss_base, self.config.module_bss_size)
        if self.config.evidence_global_base is not None:
            map_writable_region(self.config.evidence_global_base, self.config.evidence_global_size)
        self.uc.mem_map(self.config.pch_base, self.config.pch_size, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_map(self.config.mei_base, self.config.mei_size, UC_PROT_READ | UC_PROT_WRITE)
        self.host.step_to_mei_ready()
        self._sync_host_memory()

        self.uc.reg_write(UC_X86_REG_EIP, entry)
        self.uc.reg_write(UC_X86_REG_ESP, self.config.stack_top)
        self.uc.reg_write(UC_X86_REG_EBP, self.config.stack_top)
        for reg in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI):
            self.uc.reg_write(reg, 0)

        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        # The attempt-level trace already contains image identity, admission,
        # and decompression events. Append the CPU/MMIO phase to that same
        # deterministic trace instead of hiding the pre-execution evidence.
        self._trace_file = self.trace_path.open("a", encoding="utf-8")
        self._emit(
            {
                "type": "runtime_start",
                "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                "synthetic_model": False,
                "image_sha256": self.image_sha256,
                "module": module.as_dict(),
                "entry": f"0x{entry:x}",
                "module_capacity": len(module.data),
                "module_valid_extent": valid_extent,
                "evidence_global_region": (
                    {
                        "base": f"0x{self.config.evidence_global_base:x}",
                        "size": f"0x{self.config.evidence_global_size:x}",
                        "source": "real decoded module literals and metadata BSS-size correlation",
                    }
                    if self.config.evidence_global_base is not None
                    else None
                ),
            }
        )
        self._started_at = time.monotonic()
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)
        self.uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._on_memory)
        self.uc.hook_add(UC_HOOK_MEM_INVALID, self._on_invalid)
        try:
            self.uc.emu_start(entry, 0, timeout=int(self.config.timeout_seconds * 1_000_000), count=self.config.max_instructions)
            self.stop_reason = "emulator returned"
        except RealRuntimeStop as exc:
            self.stop_reason = str(exc)
        except Exception as exc:  # Unicorn error is a controlled runtime stop.
            self.stop_reason = f"emulator exception: {exc}"
        finally:
            self._emit(
                {
                    "type": "runtime_stop",
                    "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                    "synthetic_model": False,
                    "instructions": self.instructions,
                    "memory_accesses": self.memory_accesses,
                    "stop_reason": self.stop_reason,
                    "registers": self._register_dump(),
                }
            )
            self._trace_file.close()
            self._trace_file = None
        return {
            "instruction_execution_attempted": self.instructions > 0,
            "bytes_executed": self.bytes_executed,
            "instructions_executed": self.instructions,
            "memory_accesses": self.memory_accesses,
            "stop_reason": self.stop_reason,
            "trace_path": str(self.trace_path),
            "registers_at_stop": self._register_dump(),
            "faulting_instruction": self._last_instruction,
        }

    def _register_dump(self) -> dict[str, str]:
        """Return the architectural state at the current stop/fault."""

        if not UNICORN_AVAILABLE:
            return {}
        values = {
            "EAX": UC_X86_REG_EAX,
            "EBX": UC_X86_REG_EBX,
            "ECX": UC_X86_REG_ECX,
            "EDX": UC_X86_REG_EDX,
            "ESI": UC_X86_REG_ESI,
            "EDI": UC_X86_REG_EDI,
            "EBP": UC_X86_REG_EBP,
            "ESP": UC_X86_REG_ESP,
            "EIP": UC_X86_REG_EIP,
            "EFLAGS": UC_X86_REG_EFLAGS,
        }
        return {name: f"0x{int(self.uc.reg_read(reg)):08x}" for name, reg in values.items()}

    def _sync_host_memory(self) -> None:
        """Refresh mapped PCH/MEI register bytes from the host model."""

        try:
            self.uc.mem_write(self.config.pch_base, self.host.pch_snapshot())
            self.uc.mem_write(
                self.config.mei_base,
                bytes([1 if self.host.mei_ready else 0]) + bytes(self.config.mei_size - 1),
            )
        except Exception:
            # The execution path will report the original Unicorn failure if a
            # hook fires before the peripheral maps are available.
            pass


__all__ = [
    "RealRuntimeConfig",
    "RealRuntimeStop",
    "RealUnicornRuntime",
    "UNICORN_AVAILABLE",
]
