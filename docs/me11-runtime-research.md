# Public ME 11.x Runtime-Emulation Research

## Purpose

This note records public precedents that inform OpenME's research into software models of the Skylake-era Intel Management Engine (ME 11.x). It is an architectural reference, not an instruction set for bypassing platform security or running modified proprietary firmware.

The project should use these ideas only for lawful analysis, synthetic test programs, clean-room reimplementation, and controlled emulation. Original firmware remains outside the public repository. No signing bypass, authentication bypass, exploit reproduction, or firmware flashing is part of this work.

## The public precedent: meloader

The public `meloader` project is described as a Linux i386 tool for loading and executing ME modules. Its stated purpose is interoperability research and development of open alternatives, with an initial focus on the Sunrise Point/100-series chipset family. The project is not presented as a complete reproduction of the ME hardware or boot process.

The associated ME 11.x research describes the approach as similar in spirit to a compatibility layer: execute selected ME user-mode code in a normal host process while supplying the operating-system and hardware interfaces that the code expects.

Sources:

- [meloader source repository](https://github.com/peterbjornx/meloader)
- [Intel Management Engine Deep Dive slides](https://pbx.sh/intelme_talk.pdf)
- [Intel Management Engine Deep Dive talk page](https://media.ccc.de/v/36c3-10694-intel_management_engine_deep_dive)
- [Introduction to the Intel Management Engine OS, Part 2](https://pbx.sh/intelme-sw2/)

## Main components of the approach

### 1. CPU execution

ME 11.x code is executed as 32-bit x86 code in a Linux process. A CPU emulator or compatible execution environment provides the instruction semantics, registers, memory access, segmentation behavior, and controlled stepping needed by the module under study.

For OpenME, this is where an engine such as Unicorn may be useful. Unicorn can provide the instruction-execution layer, while OpenME supplies the ME-specific memory map, loader rules, callbacks, and device models. Unicorn by itself does not provide an ME operating system, ME firmware loader, PCH peripherals, HECI/MEI, or platform boot behavior.

The practical design is therefore layered:

```text
CPU execution engine
        +
ME memory and protection model
        +
ME loader and library interfaces
        +
syscall/MMIO/bus models
        +
deterministic test harness
```

### 2. Syscall and library stubs

ME modules expect services supplied by the ME operating system and its libraries. The public approach provides hooks or stubs for those dependencies instead of requiring the complete ME kernel to run.

These interfaces may cover tasks such as:

- thread and synchronization primitives;
- memory allocation and mapping;
- timers and events;
- communication endpoints;
- library dispatch tables;
- logging or trace calls; and
- controlled error returns.

The stubs should be explicit and deterministic. A stub must document its inputs, outputs, side effects, and unsupported cases. Unknown behavior should produce a visible `UNSUPPORTED` result or a controlled stop, not an invented success path.

OpenME should begin with synthetic modules and project-defined test services. It should not assume that a proprietary module's dependencies are understood merely because a symbol or filename is known.

### 3. MMIO peripheral models

ME drivers access hardware through memory-mapped I/O. The public research describes emulating these accesses and, where appropriate, forwarding selected accesses to an external process or test harness.

An OpenME MMIO model should:

- define address ranges explicitly;
- validate access width and alignment;
- record reads and writes in a replayable trace;
- return deterministic reset values;
- model only documented or experimentally justified side effects; and
- reject unmapped or unsafe accesses.

The first useful models can be small: a status register block, a timer, a mailbox, or a synthetic device that exposes controlled test behavior. More complex devices such as SPI, DMA, cryptographic accelerators, or power-management hardware should be added only when a specific research question requires them.

### 4. Bus and interconnect models

The ME is not just a CPU with a flat memory array. Public ME 11.x research describes interconnects and bus-facing services, including access to host memory and chipset peripherals. A runtime model therefore needs an abstraction for requests that leave the ME core.

A safe bus model should represent:

- request type and direction;
- target device or address space;
- width and length;
- permissions or access policy;
- completion or error status; and
- deterministic ordering.

The model should use bounded buffers and explicit ownership. DMA should initially be represented by a checked, synthetic memory-grant interface rather than unrestricted access to the host process or host machine.

### 5. Initial state and configuration

The public meloader design includes configurable hardware state and an initial state for the emulated environment. This is essential because ME modules expect particular memory regions, library vectors, segment descriptors, thread-local data, device registers, and platform configuration to exist before their entry points run.

For OpenME, initial state should be a versioned profile containing:

- CPU mode and initial registers;
- ROM, RAM, stack, and heap ranges;
- code and data mappings;
- library dispatch locations;
- segment and thread-local state;
- MMIO ranges and reset values;
- bus devices and permissions;
- interrupt and timer state; and
- a deterministic clock policy.

Profiles must be separated by platform. A Sunrise Point-LP/T460-oriented profile must not silently be treated as universal across Skylake or later systems.

### 6. Loader and metadata handling

The runtime needs a loader that understands the metadata required to place a module into the emulated address space. Public research discusses module memory maps, fixed-address library vectors, initialized data, writable areas, and MMIO ranges described by metadata.

For OpenME, the loader should first operate on synthetic module formats and metadata fixtures. Later work may inspect legally obtained firmware metadata without publishing proprietary module bytes. The loader should report every mapping and reject ambiguous or out-of-bounds records.

Loading a file into an emulator is not the same as validating it for hardware. OpenME must not claim that a module is authentic, bootable, or acceptable to a physical platform merely because it can be parsed or executed inside a test harness.

## What this precedent demonstrates

The public work demonstrates that useful ME 11.x research can be done without reproducing every hardware block at once. A focused runtime can run selected code paths when the following are supplied:

1. a compatible instruction environment;
2. a correct-enough module memory layout;
3. library and syscall interfaces;
4. MMIO and bus behavior needed by the selected path; and
5. a controlled initial hardware state.

This supports OpenME's staged strategy: start with metadata and synthetic modules, then add narrow runtime services, then connect those services to a host-facing MEI/HECI model.

## Limitations and caution

The public precedent does not prove that a complete replacement ME is already available. The research explicitly describes meloader as being built to run selected code, including `bup`, rather than as an accurate emulation of all ME hardware.

Important limitations include:

- chipset-specific addresses and peripheral behavior;
- incomplete public documentation;
- dependencies on ROM and library behavior;
- incomplete power-management and boot sequencing;
- host-memory, DMA, and interconnect semantics;
- cryptographic and secure-storage boundaries;
- differences between firmware generations and SKUs;
- missing or uncertain initialization values; and
- the inability to infer hardware acceptance from software execution alone.

The public talk also discusses security-sensitive research. OpenME does not adopt exploit-development, JTAG-unlock, chainloading, signing-bypass, or authentication-bypass activities from that material. Those topics are outside this project's initial scope.

## Responsible OpenME adaptation

OpenME should adapt the architecture in the following order:

1. Define a synthetic ME module ABI and test fixtures.
2. Validate a 32-bit x86 execution layer with deterministic traces.
3. Implement explicit syscall and library stubs.
4. Add bounded MMIO and bus models.
5. Create versioned initial-state profiles for the target platform.
6. Parse bounded CSE process-attributes metadata and use its module entry
   values only after range validation.
7. Implement verified Huffman decompression and cryptographic image admission;
   missing ROM/library state remains a hard stop.
8. Connect the runtime to an emulated host-facing MEI/HECI device and compare
   observed behavior against public documentation, clearly labeling inference.

Any future use of legally obtained firmware must remain isolated, read-only, and governed by the project's existing safety rules. No modified proprietary firmware should be executed on physical hardware, and no research result should be described as a signing or platform-authentication bypass.

## Sources and interpretation status

The sources above are public research, project documentation, and technical documentation. Statements about the design of meloader are attributed to its repository and the author's public talk and article. Statements about OpenME's proposed architecture are project design decisions, not claims about undocumented Intel implementation details.

