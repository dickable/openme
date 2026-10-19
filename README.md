# OpenME

OpenME is an open-source firmware project for the Intel Management Engine. The
goal is owner-controlled ME firmware that can, in the long term, flash and boot
on any **supported** platform — built like coreboot, with a portable core and a
per-platform porting layer, not a binary hardcoded to one board.

## Target: pre-CSME-11, ARC-core ME (generation 6 and earlier)

The hardware target is deliberately the **ARC-core ME generations (ME ≤6)** —
not Skylake. The reason is decisive:

- **Skylake / CSME 11 is locked.** Its boot ROM is mask-ROM logic in the PCH
  that verifies the firmware against RSA keys fused into the chipset. Running
  owner code there would require defeating that root of trust. OpenME does not
  do that.
- **ME ≤6 is permissive.** These generations do not have that fused-key,
  ROM-enforced wall (verify per-SKU), and on GM45-class parts the ME is even
  removable under coreboot. Running owner firmware there defeats no security
  mechanism — it is the same category as coreboot/libreboot/OpenBMC.

See **[docs/me6-target.md](docs/me6-target.md)** for the full rationale,
candidate boards, the documented footholds (HECI, firmware format), and why the
real obstacle is the undocumented ARC black box, not cryptography.

**Boundary:** OpenME forges no signatures, patches no boot ROM, and exploits or
glitches nothing. A platform that would require defeating verification to run
owner code is out of scope — not a problem to be worked around.

**No network, by construction:** OpenME has **no network stack, no AMT, and no
out-of-band remote management** — permanently. The stock ME's defining danger is
its always-on network path; OpenME removes that capability entirely, so it cannot
be remotely controlled or surveilled because it has no mechanism to be. This is
enforced structurally (the HAL exposes only a local host↔ME transport; see
`src/capabilities.h` and `src/hal/hal.h`), not merely promised.

## Architecture

A portable **core** plus a per-platform **HAL**, so adding a platform means
writing one HAL, never editing the core. See
**[docs/openme-architecture.md](docs/openme-architecture.md)**.

- `src/core.c` — OpenME's framed-v1 message/service state machine (portable).
- `src/mei/heci.c` — HBM/HECI protocol layer, transport-abstract (portable).
- `src/hal/hal.h` — the HAL interface (bringup + HECI packet recv/send).
  - `src/hal/model/` — emulation HAL used by the QEMU target.
  - `src/hal/gm45/` — first real-hardware reference port (**stub**: compiles and
    links, hardware ops return `not-implemented`, with the documented GM45/ICH9M
    register map in `gm45_regs.h`).
- `src/platform/qemu_x86/` — Multiboot entry, linker layout, and serial shell
  for the QEMU test target.

## Run the C firmware

From PowerShell in this directory:

```powershell
.\tools\launch-openme.ps1        # Visible window: build and interactive shell
.\tools\launch-openme.ps1 -Test  # Build, then automated QEMU integration test
```

The default Windows toolchain is MSYS2 UCRT64 GCC/Python. QEMU can be supplied
with `-Qemu PATH`; the launcher also detects the existing local build. This
executes compiled OpenME code in emulation — never reported as real ME
execution.

## Roadmap

1. **Pin a target** — choose a board (GM45 X200/T400 recommended first); capture
   a verified image; identify the ME version/layout (MEAnalyzer).
2. **Understand the firmware** — map FPT, modules, and the HECI service surface
   (unhuffme, me_cleaner, MEAnalyzer).
3. **Model in emulation** — reorient the QEMU core/HECI model onto the real ARC +
   HECI architecture through the HAL seam (the skeleton is in place).
4. **Design the "better ME"** — architecture and services, validated in emulation.
5. **Hardware bring-up (late, separate)** — complete the GM45 HAL; flash
   backup-first with an external SPI programmer (`tools/flash_openme.py`,
   `tools/me_neutralize.py`).

## Flashing and neutralization tools

Late-stage, backup-first, on the owner's own hardware:

- `tools/flash_openme.py` — physical SPI backup / plan / verified write.
- `tools/me_neutralize.py` — wrap upstream me_cleaner to produce a HAP'd +
  stripped image (the "disable the stock ME" path), for review before writing.

## Prior research

Skylake/CSME 11 image research is retained as reference only and is **not** the
active target: see [docs/target-platform.md](docs/target-platform.md) (marked
historical) and the analysis tree under [csme/README.md](csme/README.md).
