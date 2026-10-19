# Target platform: Intel ME generation 6 and earlier (ARC-core)

OpenME's hardware-research target is the **pre-CSME-11 Management Engine** — the
generations built on an **ARC** core, roughly **ME 1.x through ME 6.x**. This is a
deliberate choice, and it changes the project from "impossible" to "a hard but
legitimate reverse-engineering project."

## Why this generation class

The Skylake-era CSME 11 is a dead end for running owner firmware: its boot ROM is
mask-ROM logic in the PCH that verifies the firmware manifest against RSA keys
fused into the chipset, with no owner-key path. You cannot run your own code there
without defeating that root of trust, which is out of scope for this project —
OpenME does not forge signatures, patch boot ROMs, or exploit/glitch verification.

The early (ARC) generations are different in the way that matters here:

- **No silicon-fused, ROM-enforced signature wall like CSME 11's.** Integrity
  enforcement on these generations is weak and inconsistent — far from the
  fused-key model of ME 11. This means there is, in many cases, little or nothing
  to *bypass*: the hardware is permissive about what runs. **This must be verified
  per chipset/SKU**, not assumed from a blanket "ME 6 and below = no check" rule;
  confirm against the firmware-analysis tooling (below) for the exact target.
- **The community already treats these as owner-controllable.** On GM45/GS45-class
  machines (ThinkPad X200/T400), the ME can be removed entirely and the platform
  still boots under coreboot — the clearest possible evidence that these parts are
  not locked against the owner. ME 6 / 5-series (Ibex Peak) is PCH-integrated and
  more entangled with platform bring-up, but still pre-lockdown and pre-30-minute
  watchdog (that behavior arrives with ME 7.1 / Sandy Bridge).

So targeting ME ≤6 puts OpenME in the same legitimate category as coreboot,
libreboot, and OpenBMC: owner firmware on hardware that permits owner firmware,
with no security mechanism being defeated.

## The real obstacle is documentation, not cryptography

Removing the signature barrier does **not** make this easy. Nobody has a
from-scratch, functional ME replacement running on real silicon of any generation,
because the ME is an **undocumented black box**:

- The core is an **ARC processor** with no public datasheet, register map, or ISA
  reference for its ME-specific configuration.
- The firmware runs on an undocumented internal RTOS (ThreadX-based on several
  generations) with undocumented hardware blocks.
- What the ME *does* during platform bring-up (clocking, power sequencing, and on
  some platforms boot participation) is unspecified publicly.

This is why the free-firmware world *removes* the old ME rather than *replacing*
it: removal is tractable; authoring new firmware that still brings the platform up
correctly is a multi-year reverse-engineering effort. "Doable" here means "not
blocked by crypto," not "quick."

## What is actually documented (the footholds)

The project builds outward from the parts that are known:

- **The host interface (HECI / MEI).** The host-to-ME transport — the PCI device,
  the `H_CSR`/`ME_CSR` doorbell registers, and the circular-buffer message
  mechanism — is well understood from the Linux `mei` driver and the old HECI
  specification. The host side is our most solid reference surface.
- **The firmware image format.** FPT (Flash Partition Table), code partitions, and
  the Huffman-compressed modules are documented by community tooling:
  - **MEAnalyzer** (platomav) — identifies ME/CSME/TXE firmware and its structure
    across generations; use it to pin the exact ME version and layout of a target
    image.
  - **unhuffme** (Skochinsky) — the ME Huffman dictionaries, for decompressing
    modules.
  - **me_cleaner** source — the best free documentation of FPT/partition/module
    layout and the HAP/disable mechanics.
  - Igor Skochinsky's and Positive Technologies' (Ermolov/Goryachy) published ME
    static-analysis work.

## Candidate targets

The target should be chosen for how well-studied and how permissive it is, not for
what hardware happens to be nearby.

| Class | Example boards | Chipset | ME | Notes |
| --- | --- | --- | --- | --- |
| GM45 (best-studied, most permissive) | ThinkPad X200, T400, T500, X301 | GM45/GS45 + ICH9M-E | ME 4.x/5.x | ME fully removable under coreboot; libreboot flagship |
| 4-series desktop | Q45/G45 boards | 4-series + ICH10 | ME 5.x | Desktop analog of GM45 |
| Ibex Peak / 5-series (the "ME 6" target) | ThinkPad X201, T410 | QM57/QS57 | ME 6.x | First PCH-integrated ME; pre-watchdog; less studied than GM45 |

GM45 (ME 4/5) is the recommended first platform: it is the most reverse-engineered,
the ME is provably optional there, and the risk of a hard-to-recover state is
lowest. ME 6 (Ibex Peak) is the stated ceiling and a reasonable second step once
the GM45 model is solid.

## Roadmap (honest phasing)

1. **Pin the target.** Choose a specific board; capture a verified image (two
   matching read-only dumps). Identify the exact ME version and layout with
   MEAnalyzer.
2. **Understand the firmware.** Decompress and map the modules (unhuffme,
   me_cleaner layout); document the FPT, the module set, and the HECI client/service
   surface the stock firmware exposes.
3. **Model it in emulation.** Build a software model of the ME ≤6 architecture —
   the HECI transport and the service/bring-up behavior — in this repo's QEMU/Python
   environment. This is where OpenME's *design* happens, with no hardware risk. The
   current `src/` QEMU model is an abstract PC-hosted model and must be reoriented
   to the ARC/HECI architecture to be representative.
4. **Design the "better ME."** Specify the architecture, the HECI-compatible
   service model, and the security properties, validated entirely in emulation.
5. **Hardware bring-up (long-term, separate).** Only after the above, and only on a
   chosen permissive board, with backup-first flashing (see `flash_openme.py`) and
   an external SPI programmer.

## Scope and honesty boundaries

- Emulation results are a **software model**, never reported as real ME execution.
- OpenME defeats **no** security mechanism on any generation. If a chosen target
  turns out to enforce verification that would have to be bypassed to run owner
  code, that target is out of scope — not a problem to be solved with an exploit.
- Physical flashing targets **the owner's own hardware**, backup-first, and is a
  late-stage, separate activity from the emulation/design work.
