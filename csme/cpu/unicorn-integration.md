# QEMU/Unicorn Integration Design

## Status and scope

This document defines a research architecture for connecting a QEMU-emulated host platform to a separate Unicorn-backed ME runtime. It is a design proposal only. It does not claim current compatibility with Intel ME/CSME, a Lenovo T460, any particular firmware image, or any undocumented Intel interface.

The design is intentionally layered:

```text
Guest software
    |
    | PCI / MMIO / interrupts
    v
QEMU host and PCH model
    |
    | deterministic bridge messages
    v
ME runtime supervisor
    |
    | CPU execution and modeled peripherals
    v
Unicorn x86 execution engine
```

The synthetic deterministic ME-like runtime remains available as a separate
compatibility test model. The real-image path is now implemented separately
under `csme/runtime/`; it may load only bounded, verified uncompressed regions
after a verified entry point and accepted authentication state are available.
An unavailable dependency is a hard stop, not a reason to use the synthetic
model. This design does not authorize bypassing signatures, authentication,
or platform protections.

## Responsibilities

### QEMU host/PCH side

QEMU owns the emulated host machine, including:

- CPU, memory, reset, and boot sequencing;
- the PCH-facing PCI topology;
- the virtual SPI flash descriptor and region map;
- BIOS and other host-visible firmware storage;
- the host-side HECI/MEI PCI function;
- PCI configuration space, BARs, MMIO registers, interrupts, and power-state transitions;
- guest-visible timing and scheduling boundaries.

The QEMU device should expose a documented OpenME test identity during early development. A real Intel PCI identity must not be claimed until the register model and guest-driver behavior have been independently validated.

### ME runtime supervisor

The supervisor is the boundary between QEMU and Unicorn. It owns:

- runtime lifecycle and state transitions;
- virtual ME address-space allocation;
    - loading of synthetic test modules and bounded real-image module descriptions;
- syscall, MMIO, DMA, timer, and interrupt dispatch;
- bridge sequencing and validation;
- trace recording and replay;
- resource quotas and failure containment.

The supervisor is not itself an assertion that an Intel ME operating environment has been reproduced. It is an OpenME-controlled execution environment whose fidelity can be increased in stages.

### Unicorn execution engine

Unicorn owns instruction execution for the selected ME CPU mode. The integration must treat Unicorn as an execution engine rather than a complete platform model. Device behavior, memory permissions, interrupts, and external effects remain under supervisor control.

The synthetic runtime remains useful for host-model tests. Real firmware-module
support is gated by explicit format validation, provenance records, a verified
entry point, accepted authentication state, and a user-selected test profile.

## Process boundaries

The preferred architecture uses separate processes:

```text
qemu-system-x86_64
        |
        | local framed transport
        v
openme-me-runtime
        |
        | in-process API
        v
Unicorn engine
```

QEMU and the ME runtime should not share arbitrary host pointers or files. The bridge should use a local, length-delimited message transport, such as a dedicated local socket or another explicitly bounded IPC channel. The transport must have:

- a protocol version;
- message type and length fields;
- monotonically increasing sequence numbers;
- request and response identifiers;
- maximum frame and payload sizes;
- explicit status and error values;
- reset and shutdown messages;
- optional trace correlation IDs.

The separate-process boundary provides useful failure isolation: a runtime crash should terminate the virtual ME and return a controlled device error to QEMU, not corrupt the QEMU process. During early development, a deterministic in-process test adapter may be used, but it must implement the same logical bridge contract.

## Ownership and address spaces

There are four distinct memory domains:

1. **Guest physical memory**: RAM visible to the emulated CPU and guest software. QEMU owns this memory.
2. **QEMU device state**: PCI configuration, HECI queues, registers, interrupt state, and virtual SPI state. The QEMU device owns this state.
3. **ME virtual memory**: ME ROM, SRAM, heap, stacks, and mapped device windows. The runtime supervisor owns this address space and Unicorn accesses it through explicitly registered mappings.
4. **Bridge buffers**: bounded serialized payloads exchanged between QEMU and the runtime. The sender owns a buffer until the receiver acknowledges consumption; no raw pointers cross the boundary.

By default, the ME runtime must not read or write guest RAM. Host-memory access should be represented by explicit DMA requests approved by the supervisor. Each request must include direction, guest physical address, length, and an operation identifier. QEMU validates the range against the virtual machine's configured memory map before copying data into or out of a bridge-owned buffer.

The first implementation should use copy-in/copy-out DMA. Shared memory or zero-copy mappings can be considered only after correctness, bounds checking, and trace replay are established.

## HECI/MEI-side model

The QEMU device should expose a host-facing queue and register model with these conceptual responsibilities:

- guest writes to a transmit window or queue;
- QEMU validates framing and queue capacity;
- QEMU converts an accepted host message into a bridge request;
- the runtime returns a bounded response or an asynchronous event;
- QEMU places the response into the receive queue;
- QEMU updates status and interrupt state;
- guest reads and acknowledges the response.

Register offsets, bit meanings, PCI capability layout, interrupt mechanism, and client protocol details must be treated as versioned design inputs. The OpenME model should not silently present project-defined registers as Intel-compatible registers. Compatibility claims require separate evidence and guest-driver tests.

QEMU remains responsible for guest-visible ordering. A bridge response must not become visible to the guest until QEMU has applied the corresponding queue and interrupt state transition.

## MMIO handling

ME-side MMIO should be modeled through a whitelist of named virtual devices, not by allowing arbitrary host addresses. Each MMIO access should carry:

- virtual device name or numeric device ID;
- address and access width;
- read or write direction;
- value for writes;
- current runtime epoch;
- request sequence number.

The supervisor dispatches the access to a deterministic peripheral model. Unknown addresses return a defined fault or an explicit unsupported status. The model should record unknown accesses rather than inventing hardware behavior silently.

QEMU-side HECI MMIO remains local to QEMU. If a guest MMIO operation requires an ME state change, QEMU emits a bridge message; the runtime never directly handles a host pointer or QEMU memory-mapped object.

## DMA and host-memory access

DMA is a high-risk fidelity boundary and should be introduced late. The staged design is:

1. no DMA, with all runtime tests using private ME memory;
2. synthetic DMA against a small QEMU-owned test buffer;
3. bounded copy-in/copy-out requests against guest RAM;
4. permission and overlap checks;
5. only then, optional modeling of more complex asynchronous DMA behavior.

Every DMA operation must be bounded by configured maximum lengths and quotas. Invalid addresses, overflow, stale epochs, and unsupported directions must produce deterministic errors. QEMU must be able to stop the runtime before applying a response that would violate the configured memory policy.

## Interrupts and event delivery

The runtime should never directly toggle a host interrupt line. Instead:

1. the runtime emits an event such as `RX_AVAILABLE`, `TX_CONSUMED`, `DMA_COMPLETE`, or `ME_RESET_REQUIRED`;
2. QEMU validates the event against its current device state;
3. QEMU updates the virtual HECI status registers;
4. QEMU raises the configured virtual interrupt;
5. guest acknowledgment causes QEMU to clear or retain the interrupt according to the device contract.

The bridge must preserve event ordering. Interrupt coalescing, delayed delivery, and timer-driven events should be explicit configuration choices so that traces can be replayed exactly.

## Deterministic bridge contract

A bridge message should have a conceptual envelope like:

```text
magic
protocol_version
message_type
flags
epoch
sequence
request_id
payload_length
payload
```

The exact binary encoding remains an unresolved implementation choice. The logical requirements are fixed:

- reject malformed lengths before allocation;
- reject unknown protocol versions unless compatibility is explicitly enabled;
- associate every response with an epoch and request ID;
- reject responses from an old epoch after reset;
- make queue limits and timeout policy configurable;
- avoid host-time-dependent behavior in deterministic mode.

The bridge should support both request/response messages and asynchronous events. A service-step operation is preferable to unconstrained background threads during early testing. It allows a test to advance the model by one controlled event and record the resulting state.

## Trace format

The trace is an append-only sequence of structured records. JSON Lines is appropriate for inspection during early development; a compact binary representation can be added later without changing the logical schema.

Each record should include:

```json
{
  "schema": 1,
  "epoch": 3,
  "step": 42,
  "source": "qemu",
  "kind": "bridge.request",
  "request_id": 17,
  "message_type": "heci.tx",
  "payload_sha256": "...",
  "payload_length": 24,
  "result": "accepted"
}
```

Traces should record metadata and hashes by default, not proprietary firmware bytes. Payload capture should be opt-in, bounded, and clearly labeled. A replay engine must be able to run from the recorded logical messages and configuration without network access or wall-clock dependence.

Recommended record kinds include:

- `config.loaded`;
- `qemu.mmio.read` and `qemu.mmio.write`;
- `bridge.request` and `bridge.response`;
- `runtime.instruction_block`;
- `runtime.mmio`;
- `runtime.dma.request` and `runtime.dma.result`;
- `runtime.interrupt`;
- `state.transition`;
- `error.rejected`;
- `reset.begin` and `reset.end`.

Instruction tracing should be sampled or enabled only for focused tests because full instruction traces can be large. The trace must identify the runtime build, configuration hash, and bridge schema so that replay results are attributable.

## Reset and suspend/resume

### Reset

Reset is an epoch boundary:

1. QEMU stops accepting new guest-visible ME requests.
2. QEMU drains or invalidates its device queues according to the selected reset profile.
3. QEMU sends a reset request containing the new epoch.
4. The runtime stops Unicorn execution and cancels pending DMA, timers, and interrupts.
5. The runtime clears volatile ME state and returns an acknowledgment.
6. QEMU reinitializes status registers and interrupt state.
7. Guest-visible operation resumes only after both sides agree on the new epoch.

Responses from a prior epoch must be discarded. Reset handling must be testable without depending on process restart.

### Suspend/resume

Suspend and resume should initially be modeled as explicit quiesce and resume events:

- quiesce prevents new work and records outstanding operations;
- the runtime reaches a defined safe point;
- QEMU snapshots only its own state if snapshotting is enabled;
- resume restores the selected deterministic state and restarts event delivery.

Whether ME volatile state survives a platform sleep state is an unresolved fidelity question. The model should expose profiles rather than assume one behavior.

## Error isolation and resource limits

The runtime process must have bounded resources:

- maximum bridge payload;
- maximum queue depth;
- maximum DMA length and outstanding requests;
- maximum instruction steps per service call;
- maximum trace size or rotation policy;
- timeout and cancellation behavior;
- explicit memory-map limits.

Errors should be classified as protocol, validation, unsupported-feature, timeout, runtime-fault, or supervisor-fault. QEMU should convert a runtime failure into a controlled virtual-device fault and preserve a diagnostic record. The host process must not continue using stale runtime state after a fatal epoch error.

The runtime should run without network access and should not execute arbitrary host commands. Test inputs must be treated as data. Firmware bytes, if ever admitted into a test profile, must remain in an explicitly selected local path and must not be copied into tracked project files.

## Staged fidelity plan

### Stage 0: synthetic bridge

- separate-process supervisor with a no-op or scripted runtime;
- bounded framed messages;
- deterministic traces and replay;
- reset and error tests.

### Stage 1: QEMU host-facing device

- project-defined PCI identity;
- host queues, MMIO, status, interrupts, and reset;
- guest-side smoke tests;
- no Unicorn dependency required for basic regression tests.

### Stage 2: Unicorn CPU proof of concept

- synthetic x86 test code;
- private ROM/RAM mappings;
- instruction and memory hooks;
- explicit step budget and deterministic termination.

### Stage 3: supervisor peripherals

- syscall dispatch;
- named MMIO devices;
- timers and virtual interrupts;
- synthetic DMA against bounded buffers;
- trace correlation between QEMU and Unicorn.

### Stage 4: guest-visible integration

- bridge-backed HECI-like queue behavior;
- guest driver tests;
- client enumeration and controlled message exchange;
- suspend, resume, reset, timeout, and malformed-input coverage.

### Stage 5: metadata-driven firmware research

- CPD and manifest metadata validation;
- module dependency descriptions;
- loader experiments using synthetic or explicitly authorized test inputs;
- no signature bypass, authentication bypass, flashing, or claims of board compatibility.

### Stage 6: platform-specific validation

- only after the software model is useful and reproducible;
- compare against documentation and read-only observations from a sacrificial, correctly identified platform;
- preserve original images and use verified external recovery before any future modification is even considered.

## Unresolved design choices

The following choices remain open and must be decided by implementation evidence:

1. **Bridge transport**: local socket, named pipe, or another bounded IPC mechanism.
2. **Bridge encoding**: fixed binary framing, a self-describing format, or a dual human-readable/binary approach.
3. **Clock model**: instruction-count virtual time, explicit service ticks, or a hybrid timer model.
4. **QEMU integration mode**: always separate process, optional in-process adapter, or both.
5. **PCI/HECI fidelity target**: project-defined test device first, Linux MEI-compatible device next, or another guest-driver target.
6. **Unicorn CPU mode and startup state**: exact mode, reset vector, segment setup, and ABI for synthetic modules.
7. **DMA model**: copy-in/copy-out only or later shared-memory optimization.
8. **Snapshot format**: QEMU migration-compatible state, runtime-specific state, or deterministic replay instead of snapshots.
9. **Trace payload policy**: hashes-only by default versus opt-in bounded payload capture.
10. **Firmware admission policy**: preserve provenance, keep image access
    read-only, and require separate evidence for every executable region and
    entry point.

## Non-goals

This design does not:

- claim that Unicorn alone can emulate Intel ME;
- claim that the current QEMU device is HECI/MEI-compatible;
- provide a universal Skylake firmware implementation;
- bypass signature verification, Boot Guard, platform authentication, or access controls;
- instruct anyone to flash experimental firmware;
- replace hardware validation, recovery planning, or provenance checks.

