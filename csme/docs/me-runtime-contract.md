# OpenME ME Runtime Contract

This document defines the backend-neutral boundary for a future synthetic ME
runtime. It is intentionally independent of Unicorn and any other CPU
emulator. The contract lets OpenME test memory, registers, host services,
MMIO, interrupts, tracing, snapshots, and reset behavior before choosing or
implementing a CPU backend.

## Safety boundary

The contract is for synthetic state only. It does not load firmware, parse the
private SPI dump, execute proprietary modules, access hardware, bypass
signatures, or contact external services. A backend must not silently turn
these interfaces into a firmware-admission mechanism.

## Runtime components

`RuntimeState` owns five explicit services:

- `SyntheticMemory`: named ROM/RAM regions with bounds checks, read-only ROM,
  mutable RAM, and complete snapshots.
- `Registers`: named integer registers with deterministic initialization and
  snapshot/restore.
- `Syscalls`: numbered handlers returning a structured `SyscallResult`.
- `MMIOBus`: non-overlapping windows that dispatch bounded reads and writes to
  registered handlers.
- `InterruptController`: FIFO pending interrupts with snapshot/restore.

The contract does not assign real Intel ME register numbers, syscall numbers,
or MMIO addresses. Those are platform observations or future design choices,
not assumptions made here.

## Backend boundary

`RuntimeBackend` is the only CPU-facing interface. A backend must implement:

1. `reset(runtime)` to reset backend-private state.
2. `execute_step(runtime, instruction_budget)` to perform a bounded,
   deterministic execution step and return `BackendStep`.
3. `snapshot(runtime)` to serialize backend-private state.
4. `restore(runtime, snapshot)` to restore that state.

A future Unicorn adapter can map its CPU registers and memory accesses onto
the `RuntimeState` services. The rest of OpenME should depend on this contract
instead of importing a Unicorn API directly.

## Determinism rules

- Execution is driven only by an explicit positive instruction budget.
- Runtime state changes occur through the state services or the backend.
- No wall-clock time, random values, host filesystem, network, or threads are
  implicit inputs.
- Snapshots include memory, registers, pending interrupts, step index, halted
  state, and backend-private bytes.
- Replaying from the same snapshot with the same backend inputs must produce
  the same step result and state.
- Trace fields are sorted and represented as strings for stable comparison.

## Reset and snapshots

The runtime captures an initial snapshot at construction. `reset()` restores
that snapshot, resets backend-private state, clears the step counter, and
leaves the runtime running. `snapshot()` and `restore()` are intended for
deterministic tests, trace replay, and future checkpointing; they are not a
firmware persistence format.

## Tracing

An optional `TraceSink` receives immutable `TraceEvent` values. The orchestration
layer emits `step_begin`, `step_end`, `step` for a halted call, `reset`, and
`restore`. A CPU backend may add instruction, memory, syscall, MMIO, and
interrupt events through the same sink once the event vocabulary is defined.

## Future integration order

1. Keep the current synthetic backend and contract tests passing.
2. Add a backend adapter that executes only synthetic test code.
3. Add explicit syscall/MMIO/interrupt adapters with deterministic fixtures.
4. Add QEMU-side transport only after the standalone runtime is reproducible.
5. Review any future firmware-admission policy separately; this contract does
   not authorize firmware loading or execution.
