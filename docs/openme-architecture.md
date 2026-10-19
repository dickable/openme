# OpenME internal architecture (portability model)

The goal is for OpenME to flash and boot on **any supported ME ≤6 platform**, not a
hardcoded list of boards. That generality is not something you bolt on later — it
is a structural decision made now: OpenME is split into a **hardware-independent
core** and a per-platform **HAL (hardware abstraction layer)**, exactly the way
coreboot separates its common code from per-mainboard support.

Breadth is then earned one port at a time. The architecture makes a new platform a
*port* (implement a HAL) rather than a rewrite. It does not make breadth free — see
"Honest expectations" below.

## Layers

```
            +-------------------------------------------------+
            |  Core  (portable, no chipset knowledge)         |
            |  - HECI message dispatch                        |
            |  - service model ("the better ME" logic)        |
            |  - connection / flow-control state machine      |
            |  - cooperative scheduler, timers                |
            +------------------------+------------------------+
                                     |  message + abstract-HW API
            +------------------------v------------------------+
            |  HAL  (one implementation per ME gen / chipset)  |
            |  - ARC core bring-up                             |
            |  - HECI transport: H_CSR/ME_CSR + circular bufs  |
            |  - clock / power sequencing                      |
            |  - chipset MMIO register map (addresses/bits)    |
            +------------------------+------------------------+
                                     |
            +------------------------v------------------------+
            |  Image / packaging                              |
            |  - FPT + partition layout for the target's      |
            |    flash region; produces a flashable image     |
            +-------------------------------------------------+
```

- **Core** contains everything that is the *same* on every platform: the HECI
  protocol handling, the service/dispatch logic, the connection and flow-control
  state machines, scheduling. It knows nothing about a specific chipset. This is
  where the "better ME" design lives, and it is written and tested once.
- **HAL** is the only layer that changes per platform. It is a defined interface
  the core calls: "bring the core up," "a message arrived," "send these bytes,"
  "sequence this power transition," plus the register map for that chipset. A new
  supported platform == a new HAL implementation satisfying that interface.
- **HECI transport abstraction** is the seam between them. The core speaks in
  whole messages; the HAL maps that onto the real `H_CSR`/`ME_CSR` doorbell
  registers and circular buffers of the target. Because the host-side HECI
  mechanism is the best-documented part of the ME, this seam is the most stable.
- **Image/packaging** turns a built core+HAL into an FPT-structured image matching
  the target's flash region, for the (late-stage, backup-first) write workflow.

## Supported-platforms registry

Generality is tracked as an explicit, honest list — a platform is "supported" only
at the status it has actually reached:

| Platform | ME gen | HAL status | Validation |
| --- | --- | --- | --- |
| GM45 (X200/T400) | 4/5 | not started | — |
| 4-series desktop (Q45) | 5 | not started | — |
| Ibex Peak (X201/T410) | 6 | not started | — |

Status progression per platform: `not started` → `HAL stub (emulated)` →
`core boots in emulation` → `hardware-validated`. Nothing is listed as
"flash and boot" until it is `hardware-validated` on that exact platform.

## Why one reference port first, not "both" up front

The right order is: **(1)** build the core + the HAL *interface* against emulation,
**(2)** complete one real HAL (GM45) as the reference port, **(3)** then expand to
Ibex Peak and others by writing more HALs. Implementing breadth before one target
works end-to-end is how firmware projects stall — you accumulate half-finished
platform code with nothing that boots.

So "implement both" becomes: *design for both (and more) now by getting the
core/HAL split right, implement GM45 first, and let the supported list grow one
validated HAL at a time.*

## Honest expectations

coreboot is the proof that the portable-core + per-board model works across many
machines — and the warning about cost. coreboot took roughly two decades and a
large community to reach its board list, and it had far more documentation to work
from than the ME offers. A portable ME replacement is harder per platform, because
each HAL is reverse-engineered from an undocumented ARC coprocessor (see
[me6-target.md](me6-target.md)). The architecture here is what makes "any supported
platform" *possible and maintainable*; it is not a claim that many platforms will
be supported quickly. Each entry in the registry above is a real project.

## Boundary

The HAL brings a platform up on hardware that *permits* owner firmware (no enforced
verification to defeat). OpenME implements no bypass of any security mechanism on
any generation; a platform that would require defeating verification to run owner
code does not get a HAL. Emulation results are never reported as real ME execution.

**No-network invariant.** OpenME has no network stack, no AMT, and no out-of-band
remote management — permanently (`src/capabilities.h`). This is the project's core
trust property: the stock ME is feared because it is an always-on, network-capable,
OS-invisible computer, so OpenME removes the network capability by construction.
It is enforced in the architecture: the HAL exposes only a local host↔ME transport
(HECI recv/send), bring-up, and a tick source — no NIC, no off-die comms, and none
may ever be added. A firmware that cannot reach a network cannot be remotely
controlled, which is a property you verify by reading the source.
