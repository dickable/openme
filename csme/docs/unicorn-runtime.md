# Unicorn runtime proof of concept

This document describes the small optional CPU-runtime experiment in
`csme/cpu/unicorn_runtime.py`.

## Purpose

The proof of concept tests whether OpenME can use Unicorn as a deterministic
x86 instruction-execution layer for future ME research. It is deliberately a
runtime seam, not an Intel ME emulator and not a firmware loader.

The current experiment uses only synthetic 32-bit x86 instructions created in
the test file. It does not open, extract, execute, or modify the private SPI
dump or any other firmware image. It does not bypass signatures,
authentication, or platform security.

## What it provides

When the optional `unicorn` Python package is present, the adapter:

- creates a 32-bit x86 Unicorn engine;
- maps deterministic code, data, and stack pages;
- initializes EIP, ESP, EBP, EAX, and EBX to known values;
- loads caller-supplied synthetic instruction bytes only;
- runs code with optional stop-address and instruction-count controls;
- records instruction-execution events;
- records mapped memory reads and writes; and
- exposes listener callbacks for later trace collection.

The test program stores `0x12345678` at synthetic address `0x2000`, reads it
back, doubles it in EAX, and halts. This validates the execution and tracing
seam without relying on an assembler or proprietary bytes.

## What it does not provide

Unicorn supplies CPU instruction execution, not the surrounding ME platform.
OpenME would still need separately evidenced models for memory ownership,
MMIO, DMA, interrupts, timers, bus services, module loading, HECI/MEI, and
host boot interactions. Those are future research tasks and must not be
assumed to match Intel behavior without documentation or observation.

The adapter intentionally has no firmware-file input, CPD loader, signature
handling, or native hardware access. It is therefore safe to run against
synthetic test bytes only.

## Optional dependency behavior

Unicorn is not bundled with OpenME and this change does not download it. If
the package is unavailable, importing the adapter still works, its tests skip
the execution cases with a clear reason, and constructing `UnicornRuntime`
raises `UnicornUnavailableError`. This keeps the rest of the project usable
without making Unicorn a mandatory dependency.

Run the focused tests from the repository root with:

```powershell
python -m unittest -v csme.tests.test_unicorn_runtime
```

The test suite is intentionally limited to this proof of concept. A passing
test run demonstrates synthetic CPU execution and deterministic tracing; it
does not demonstrate Intel ME compatibility.
