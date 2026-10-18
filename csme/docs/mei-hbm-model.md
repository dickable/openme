# Synthetic MEI/HBM host model

This document describes the small host-side transport model in
`csme/mei/mei_hbm.py`. It is intentionally synthetic. It does not load,
extract, execute, or modify Intel ME firmware and it does not claim to be an
implementation of undocumented Intel hardware.

## Why this model exists

Public Linux MEI documentation describes a host-facing device with a host bus
message (HBM) control path, host/ME readiness and reset state, circular message
buffers, interrupts, client traffic, and completion handling. The model turns
those observable transport concepts into deterministic Python behavior so the
OpenME project can test host-side state machines before adding a QEMU PCI
device or any hardware work.

Reference documentation:

- [Linux MEI driver API](https://docs.kernel.org/driver-api/mei/mei.html)

The model is not a copy of Intel register definitions. Register offsets,
silicon-specific status bits, firmware services, authentication, and platform
boot dependencies remain outside its scope.

## State and readiness

Both sides start in `reset`:

```text
host: reset       ME: reset       traffic: rejected
host: ready       ME: reset       traffic: rejected
host: ready       ME: ready       traffic: accepted
```

`reset()` clears both sides, both circular buffers, interrupt causes, and the
sequence counter. `set_host_ready()` and `set_me_ready()` expose the two halves
of the synthetic handshake. `set_ready()` is only a test convenience.

## Circular-buffer slots

There are two fixed-capacity rings:

```text
host -> ME:   HostMessage(sequence, opcode, payload)
ME -> host:   Completion(sequence, opcode, status, payload)
```

Each ring has a read index, write index, occupancy count, and fixed slot
capacity. Indices wrap modulo the slot count. A request is never silently
dropped: attempting to write a full input ring raises `BufferFullError`, and a
service pass leaves an input request queued when the output ring is full.

The default synthetic slot is 64 bytes with an 8-byte conceptual header, so
the default payload limit is 56 bytes. This is a model parameter, not a claim
about a particular MEI hardware MTU.

## Interrupts

The model exposes two latched causes:

- `ME_INPUT`: the host placed a message in the host-to-ME ring.
- `HOST_INPUT`: the ME placed a completion in the ME-to-host ring.

They are intentionally named for the peer that should service the new data.
`ack_interrupts()` clears selected causes explicitly. Reading a completion does
not implicitly clear the host interrupt, making acknowledgement observable in
tests.

## Completion behavior

`me_service()` is a deterministic stand-in for ME-side work. For every
accepted request it emits a status-0 completion with the same sequence,
opcode, and payload. This echo behavior is a test oracle only; it is not an
Intel ME service and does not imply that real HBM commands echo payloads.

`ServiceReport` records how many messages were processed and whether output
capacity blocked further progress. This makes backpressure and queue sizing
testable without sleeps, threads, or external devices.

## Deliberate limits

This model does not implement:

- Intel PCI configuration space or BAR registers
- Actual MEI register bit definitions
- HBM command or response IDs
- GUID-based ME client enumeration
- DMA, interrupts at the electrical level, or power management
- Firmware loading, signing, authentication, or boot policy
- A real ME runtime or replacement firmware

Those are separate research tasks. Keeping this layer deterministic and
synthetic prevents accidental coupling to private firmware bytes or claims
about behavior that the public documentation does not establish.

## Focused test

From the repository root, run:

```text
python -m unittest -v csme.tests.test_mei_hbm
```

The tests cover readiness gating, ring wrap-around, latched interrupts,
completion correlation, bounded input/output queues, payload limits, and reset
isolation.
