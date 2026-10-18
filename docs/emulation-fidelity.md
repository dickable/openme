# Emulation fidelity plan

## Correction to the initial assumption

The statement that QEMU cannot faithfully emulate Intel ME was too absolute.
QEMU is an extensible system emulator, and the public research record shows
that ME 11.x modules can be run under controlled software emulation. The right
question is not whether emulation is possible in principle, but which fidelity
level OpenME can reproduce and validate for the selected Skylake platform.

The current OpenME device is only a deterministic test model. It is not yet a
faithful Intel ME implementation.

## Evidence and terminology

The Linux MEI documentation describes the host-facing interface as a PCI
device, with message-based clients identified by GUIDs and client-specific
protocols. That gives OpenME a documented starting point for a real host-facing
compatibility layer.

Public ME 11.x research covering the Skylake/Kaby Lake era describes `meloader`,
a controlled loader that runs unmodified ME user-mode binaries under Linux,
with syscall stubs, MMIO peripheral emulation, bus emulation, and configurable
initial state. The same research explicitly distinguishes this from accurate
full hardware emulation. That distinction is useful: it demonstrates a viable
runtime-emulation direction without pretending the whole platform is solved.

## Fidelity ladder

### Level 0: deterministic fake model

This is the current implementation. It has project-defined commands, bounded
frames, queues, state transitions, and traces. It is useful for test harnesses
but is not Intel-compatible.

### Level 1: host-facing MEI/HECI compatibility

Implement the actual host-visible shape for the selected Skylake PCH model:

- Correct PCI function identity for the chosen reference platform
- PCI configuration space and BAR layout
- Interrupt and reset behavior
- Firmware-status registers
- Host-bus message framing and flow control
- MEI client enumeration by GUID
- Client connection, protocol version, and maximum-message negotiation

This can be tested first with the Linux MEI driver and small user-space test
clients inside QEMU, without loading proprietary ME firmware.

### Level 2: ME runtime emulation

Build a lawful, isolated execution environment for selected ME 11.x modules or
equivalent reimplemented components. This requires modeling the ME CPU/runtime,
memory layout, syscalls, module metadata, MMIO, bus access, and initial state.
No signature bypass or security-protection bypass is part of this plan.

### Level 3: platform-service fidelity

Add only the services demonstrated to be required by the selected platform:

- HECI clients and host-visible status
- Host memory grants and DMA semantics in a controlled model
- SPI and sideband access models
- Power-management and reset interactions
- Required PCH and PMC behavior

Each service needs an explicit test and evidence source. Names found in a
firmware directory are not sufficient evidence by themselves.

### Level 4: boot and differential fidelity

Run a Skylake-compatible host firmware environment and compare observable
behavior against a legally obtained reference machine or documented traces.
This is where Boot Guard, fTPM, signed-image enforcement, power sequencing,
and platform-specific assumptions become major boundaries.

## Current project position

OpenME is between Level 0 and the beginning of Level 1. The SPI, ME partition,
and CPD parsers provide the image-structure foundation. The next implementation
should replace the project-defined PCI identity with a selectable, documented
reference-platform profile in a separate experimental device, while keeping
the existing fake device for deterministic regression tests.

## Safety boundary

The emulation work remains software-only. Original dumps stay preserved and
ignored, no firmware is flashed, and the project does not attempt to defeat
signature verification, platform authentication, Boot Guard, or other security
controls.

## References

- Linux kernel MEI documentation: <https://www.kernel.org/doc/html/latest/driver-api/mei/mei.html>
- Peter Bosch, Intel Management Engine Deep Dive: <https://media.ccc.de/v/36c3-10694-intel_management_engine_deep_dive>
- ME 11.x research slides and `meloader` description: <https://pbx.sh/intelme_talk.pdf>
- Open-source SPI flash emulator/monitor: <https://github.com/osresearch/spispy>
