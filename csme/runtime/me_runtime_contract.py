"""Backend-neutral contract for a deterministic, synthetic ME runtime.

This module deliberately contains no firmware loader and no CPU emulator
dependency.  A future backend (for example, a Unicorn adapter) should use
these interfaces rather than coupling the rest of OpenME to one emulator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Mapping, Optional, Protocol, Sequence, Tuple


class ContractError(ValueError):
    """Raised when a contract invariant is violated."""


@dataclass(frozen=True)
class MemoryRegion:
    name: str
    base: int
    size: int
    readonly: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise ContractError("memory region name must not be empty")
        if self.base < 0 or self.size <= 0:
            raise ContractError("memory region must have a non-negative base and positive size")

    @property
    def end(self) -> int:
        return self.base + self.size


MemorySnapshot = Tuple[Tuple[str, int, int, bool, bytes], ...]
RegisterSnapshot = Tuple[Tuple[str, int], ...]


class SyntheticMemory(Protocol):
    """ROM/RAM interface.  Implementations must reject unmapped access."""

    def map_region(self, region: MemoryRegion, initial: bytes = b"") -> None: ...

    def read(self, address: int, size: int) -> bytes: ...

    def write(self, address: int, data: bytes) -> None: ...

    def snapshot(self) -> MemorySnapshot: ...

    def restore(self, snapshot: MemorySnapshot) -> None: ...


class DeterministicMemory:
    """Small synthetic memory map with explicit ROM and RAM permissions."""

    def __init__(self) -> None:
        self._regions: Dict[str, MemoryRegion] = {}
        self._data: Dict[str, bytearray] = {}

    def map_region(self, region: MemoryRegion, initial: bytes = b"") -> None:
        if region.name in self._regions:
            raise ContractError(f"duplicate memory region: {region.name}")
        if len(initial) > region.size:
            raise ContractError(f"initial data exceeds region {region.name}")
        for other in self._regions.values():
            if region.base < other.end and other.base < region.end:
                raise ContractError(f"memory regions overlap: {region.name} and {other.name}")
        self._regions[region.name] = region
        self._data[region.name] = bytearray(region.size)
        self._data[region.name][: len(initial)] = initial

    def regions(self) -> Tuple[MemoryRegion, ...]:
        return tuple(sorted(self._regions.values(), key=lambda item: item.base))

    def _locate(self, address: int, size: int) -> Tuple[MemoryRegion, int]:
        if address < 0 or size < 0:
            raise ContractError("memory address and size must be non-negative")
        for region in self._regions.values():
            if region.base <= address and address + size <= region.end:
                return region, address - region.base
        raise ContractError(f"unmapped or cross-region memory access at 0x{address:x}")

    def read(self, address: int, size: int) -> bytes:
        region, offset = self._locate(address, size)
        return bytes(self._data[region.name][offset : offset + size])

    def write(self, address: int, data: bytes) -> None:
        payload = bytes(data)
        region, offset = self._locate(address, len(payload))
        if region.readonly:
            raise ContractError(f"write to read-only region: {region.name}")
        self._data[region.name][offset : offset + len(payload)] = payload

    def snapshot(self) -> MemorySnapshot:
        return tuple(
            (region.name, region.base, region.size, region.readonly, bytes(self._data[region.name]))
            for region in self.regions()
        )

    def restore(self, snapshot: MemorySnapshot) -> None:
        if tuple((r.name, r.base, r.size, r.readonly) for r in self.regions()) != tuple(
            (name, base, size, readonly) for name, base, size, readonly, _ in snapshot
        ):
            raise ContractError("memory snapshot layout does not match runtime")
        for name, _, _, _, data in snapshot:
            if len(data) != len(self._data[name]):
                raise ContractError(f"memory snapshot size mismatch for {name}")
            self._data[name][:] = data


class Registers(Protocol):
    """Named-register interface with deterministic snapshot/restore."""

    def get(self, name: str) -> int: ...

    def set(self, name: str, value: int) -> None: ...

    def snapshot(self) -> RegisterSnapshot: ...

    def restore(self, snapshot: RegisterSnapshot) -> None: ...


class RegisterFile:
    def __init__(self, names: Iterable[str], initial: Optional[Mapping[str, int]] = None) -> None:
        self._values = {name: 0 for name in names}
        if len(self._values) == 0:
            raise ContractError("at least one register is required")
        if initial:
            for name, value in initial.items():
                self.set(name, value)

    def get(self, name: str) -> int:
        if name not in self._values:
            raise ContractError(f"unknown register: {name}")
        return self._values[name]

    def set(self, name: str, value: int) -> None:
        if name not in self._values:
            raise ContractError(f"unknown register: {name}")
        if not isinstance(value, int) or value < 0:
            raise ContractError("register values must be non-negative integers")
        self._values[name] = value

    def snapshot(self) -> RegisterSnapshot:
        return tuple(sorted(self._values.items()))

    def restore(self, snapshot: RegisterSnapshot) -> None:
        if tuple(sorted(self._values)) != tuple(name for name, _ in sorted(snapshot)):
            raise ContractError("register snapshot layout does not match runtime")
        for name, value in snapshot:
            self.set(name, value)


@dataclass(frozen=True)
class SyscallRequest:
    number: int
    arguments: Tuple[int, ...] = ()


@dataclass(frozen=True)
class SyscallResult:
    return_value: int = 0
    data: bytes = b""
    status: str = "ok"


SyscallHandler = Callable[[SyscallRequest], SyscallResult]


class Syscalls(Protocol):
    def register(self, number: int, handler: SyscallHandler) -> None: ...

    def dispatch(self, request: SyscallRequest) -> SyscallResult: ...


class SyscallDispatcher:
    def __init__(self) -> None:
        self._handlers: Dict[int, SyscallHandler] = {}

    def register(self, number: int, handler: SyscallHandler) -> None:
        if number < 0 or number in self._handlers:
            raise ContractError("syscall number must be unique and non-negative")
        self._handlers[number] = handler

    def dispatch(self, request: SyscallRequest) -> SyscallResult:
        handler = self._handlers.get(request.number)
        if handler is None:
            return SyscallResult(return_value=-1, status="unsupported")
        result = handler(request)
        if not isinstance(result, SyscallResult):
            raise ContractError("syscall handlers must return SyscallResult")
        return result


@dataclass(frozen=True)
class MMIOAccess:
    address: int
    size: int
    write: bool
    value: int = 0


class MMIOHandler(Protocol):
    def read(self, access: MMIOAccess) -> int: ...

    def write(self, access: MMIOAccess) -> None: ...


@dataclass(frozen=True)
class MMIOWindow:
    base: int
    size: int
    handler: MMIOHandler

    @property
    def end(self) -> int:
        return self.base + self.size


class MMIOBus:
    def __init__(self) -> None:
        self._windows: list[MMIOWindow] = []

    def map(self, base: int, size: int, handler: MMIOHandler) -> None:
        if base < 0 or size <= 0:
            raise ContractError("MMIO window must have a non-negative base and positive size")
        window = MMIOWindow(base, size, handler)
        if any(window.base < item.end and item.base < window.end for item in self._windows):
            raise ContractError("MMIO windows overlap")
        self._windows.append(window)
        self._windows.sort(key=lambda item: item.base)

    def _find(self, address: int, size: int) -> MMIOWindow:
        for window in self._windows:
            if window.base <= address and address + size <= window.end:
                return window
        raise ContractError(f"unmapped MMIO access at 0x{address:x}")

    def read(self, address: int, size: int) -> int:
        window = self._find(address, size)
        return window.handler.read(MMIOAccess(address, size, False))

    def write(self, address: int, size: int, value: int) -> None:
        window = self._find(address, size)
        window.handler.write(MMIOAccess(address, size, True, value))


@dataclass(frozen=True)
class Interrupt:
    vector: int
    payload: bytes = b""


InterruptSnapshot = Tuple[Interrupt, ...]


class InterruptController:
    def __init__(self) -> None:
        self._pending: list[Interrupt] = []

    def raise_interrupt(self, interrupt: Interrupt) -> None:
        if interrupt.vector < 0:
            raise ContractError("interrupt vector must be non-negative")
        self._pending.append(interrupt)

    def pop(self) -> Optional[Interrupt]:
        return self._pending.pop(0) if self._pending else None

    def pending(self) -> InterruptSnapshot:
        return tuple(self._pending)

    def snapshot(self) -> InterruptSnapshot:
        return self.pending()

    def restore(self, snapshot: InterruptSnapshot) -> None:
        self._pending = list(snapshot)


@dataclass(frozen=True)
class TraceEvent:
    step: int
    kind: str
    fields: Tuple[Tuple[str, str], ...] = ()


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None: ...


class ListTraceSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class BackendStep:
    instructions: int = 0
    cycles: int = 0
    halted: bool = False
    reason: str = "completed"


@dataclass(frozen=True)
class RuntimeSnapshot:
    memory: MemorySnapshot
    registers: RegisterSnapshot
    interrupts: InterruptSnapshot
    step_index: int
    halted: bool
    backend: bytes = b""


class RuntimeBackend(Protocol):
    """Adapter boundary for a future CPU backend."""

    def reset(self, runtime: "RuntimeState") -> None: ...

    def execute_step(self, runtime: "RuntimeState", instruction_budget: int) -> BackendStep: ...

    def snapshot(self, runtime: "RuntimeState") -> bytes: ...

    def restore(self, runtime: "RuntimeState", snapshot: bytes) -> None: ...


@dataclass
class RuntimeState:
    memory: SyntheticMemory
    registers: Registers
    syscalls: Syscalls
    mmio: MMIOBus
    interrupts: InterruptController


class MERuntimeContract:
    """Deterministic orchestration layer shared by all CPU backends."""

    def __init__(
        self,
        state: RuntimeState,
        backend: RuntimeBackend,
        trace: Optional[TraceSink] = None,
    ) -> None:
        self.state = state
        self.backend = backend
        self.trace = trace
        self.step_index = 0
        self.halted = False
        self._initial = self.snapshot()

    def _emit(self, kind: str, **fields: object) -> None:
        if self.trace is not None:
            self.trace.emit(
                TraceEvent(
                    self.step_index,
                    kind,
                    tuple(sorted((key, str(value)) for key, value in fields.items())),
                )
            )

    def step(self, instruction_budget: int = 1) -> BackendStep:
        if instruction_budget <= 0:
            raise ContractError("instruction budget must be positive")
        if self.halted:
            result = BackendStep(reason="halted", halted=True)
            self._emit("step", reason=result.reason)
            return result
        self._emit("step_begin", budget=instruction_budget)
        result = self.backend.execute_step(self.state, instruction_budget)
        if not isinstance(result, BackendStep):
            raise ContractError("backend must return BackendStep")
        self.step_index += 1
        self.halted = result.halted
        self._emit("step_end", instructions=result.instructions, reason=result.reason)
        return result

    def reset(self) -> None:
        self.state.memory.restore(self._initial.memory)
        self.state.registers.restore(self._initial.registers)
        self.state.interrupts.restore(self._initial.interrupts)
        self.backend.restore(self.state, self._initial.backend)
        self.backend.reset(self.state)
        self.step_index = 0
        self.halted = False
        self._emit("reset")

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            memory=self.state.memory.snapshot(),
            registers=self.state.registers.snapshot(),
            interrupts=self.state.interrupts.snapshot(),
            step_index=self.step_index,
            halted=self.halted,
            backend=self.backend.snapshot(self.state),
        )

    def restore(self, snapshot: RuntimeSnapshot) -> None:
        self.state.memory.restore(snapshot.memory)
        self.state.registers.restore(snapshot.registers)
        self.state.interrupts.restore(snapshot.interrupts)
        self.backend.restore(self.state, snapshot.backend)
        self.step_index = snapshot.step_index
        self.halted = snapshot.halted
        self._emit("restore")

