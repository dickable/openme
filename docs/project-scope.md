# Project scope

OpenME's hardware-research target is the **pre-CSME-11, ARC-core Management Engine
(ME generation 6 and earlier)** — see [me6-target.md](me6-target.md) for why, the
candidate boards, and the roadmap. These generations are not locked against owner
firmware the way Skylake/CSME 11 is, so the project runs owner code on permissive
hardware rather than defeating any security mechanism. Earlier Skylake/ME 11 image
research (`target-platform.md`, artifacts under `csme/`) is retained as reference
only; it is not the active target. The firmware source lives under `src/`, with a
QEMU test target and a separate, late-stage physical-flashing workflow.

The research will focus on:

- SPI flash regions and their layout.
- ME metadata and firmware-image structure.
- Host-to-ME interfaces and observable message behavior.
- Boot dependencies, power-management interactions, and platform initialization.
- Reproducible parsers, fixtures, tests, and software models.

Writable-copy firmware experiments, source-built firmware, and physical
flashing are in scope on the owner's own permissive hardware, backup-first.
Preserve a baseline for reproducibility and record changes and observations.
Distinguish emulator admission choices from observed firmware behavior and
physical hardware behavior. A shell in the QEMU target establishes C code
execution, not a complete ME replacement or a hardware boot. No synthetic-model
result is reported as real ME execution. OpenME defeats no security mechanism on
any ME generation; a target that would require bypassing verification to run
owner code is out of scope.

