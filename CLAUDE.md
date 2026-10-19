# OpenME — context for Claude

Open-source firmware for the Intel Management Engine. Long-term goal: owner
firmware that flashes and boots on any **supported** platform, structured like
coreboot (portable core + per-platform HAL).

## Read first

- [README.md](README.md) — overview and how to run.
- [docs/me6-target.md](docs/me6-target.md) — the target decision and why.
- [docs/openme-architecture.md](docs/openme-architecture.md) — core/HAL design.

## Target and the hard boundary (do not drift from this)

- **Target is the ARC-core ME, generation 6 and earlier.** These parts are
  permissive — no fused-key, ROM-enforced signature wall (verify per-SKU), ME
  often removable. Running owner firmware there defeats no security mechanism.
- **Skylake / CSME 11 is explicitly out of scope** as a run target: its root of
  trust is fused into the PCH silicon. It stays as reference research only.
- **OpenME defeats no verification, ever.** No forged signatures, no boot-ROM
  patching, no exploits, no fault injection. If a platform would require
  bypassing a check to run owner code, it does **not** get a HAL — it is out of
  scope, not a problem to solve. This boundary is the project's foundation; keep
  work on the permissive-hardware / emulation / neutralize side of it.
- The genuine difficulty is the **undocumented ARC core**, not cryptography —
  which is why the plan is understand → emulate → design, and hardware is late.
- **No-network invariant (hard rule):** OpenME has no network stack, no AMT, no
  out-of-band remote management — permanently (`src/capabilities.h`,
  `OPENME_CAP_NETWORK = 0`). This is the core trust property; the HAL deliberately
  exposes only a local host↔ME transport. Never add a network/NIC/off-die op to
  the HAL or a service. `boot` reports `net=none` and the test asserts it.
- **Dormant-by-default (hard rule):** firmware boots with `powered = 0` and
  `om_firmware_service_once` does nothing until `om_firmware_power(fw, 1)` (the
  S0/power-button signal). Unlike the stock ME, OpenME services nothing in
  standby/off. The `gate` command/test proves it (host message ignored while
  dormant, serviced after power-on). A real port drives `powered` from the
  detected host power state. (Silicon power timing is a hardware/board matter;
  this is the firmware policy and it's what makes "only runs when on" true.)

## Layout

- `src/core.c`, `src/core.h` — portable framed-v1 message/service state machine.
- `src/mei/heci.c`, `heci.h` — portable HBM/HECI protocol layer (transport-abstract).
- `src/hal/hal.h` — HAL interface: `bringup`, `recv`, `send` (one impl per platform).
  - `src/hal/model/model_hal.c` — emulation HAL (in-memory loopback); QEMU uses this.
  - `src/hal/gm45/` — first reference port, **stub** (hardware ops return
    `not-implemented`); `gm45_regs.h` has the documented GM45/ICH9M HECI registers.
- `src/fs/flashfs.c`, `flashfs.h` — OpenME's own embedded flash filesystem
  (EFFS/MFS-equivalent): log-structured key→value store over NOR semantics.
  `nor_model.c` is the RAM-backed NOR model for emulation (enforces 1→0-only writes).
- `src/platform/support.c`, `support.h` — supported-platform registry + guard
  (`om_platform_check`): warns/refuses on out-of-scope hardware (CSME 11+, unknown).
- `src/firmware.c`, `firmware.h` — top-level `om_firmware_boot`: staged bring-up
  (platform guard → HAL → filesystem → HECI), platform-independent.
- `src/platform/qemu_x86/` — Multiboot entry (`start.S`), `link.ld`, serial shell (`main.c`).
- `tools/build_openme.py` — freestanding build (MSYS2 UCRT64 GCC, `-Werror`).
- `tools/run_openme_qemu.py` — QEMU integration test (strict byte-exact assertions).
- `tools/flash_openme.py` — physical SPI backup/plan/verified-write (late stage).
- `tools/me_neutralize.py` — wraps upstream me_cleaner (HAP + strip). Needs an
  external me_cleaner.py via `--me-cleaner`.
- `csme/` — prior Skylake/ME 11 analysis (reference only, not the active target).

## Build / test

```powershell
.\tools\launch-openme.ps1 -Test   # build + QEMU integration test
# or directly:
& C:\msys64\ucrt64\bin\python.exe tools\build_openme.py
& C:\msys64\ucrt64\bin\python.exe tools\run_openme_qemu.py --qemu <path-to-qemu-system-x86_64>
```

The repo's QEMU build is at `qemu-work\qemu-source-clean\build\qemu-system-x86_64.exe`.
The Python test suite under `csme/`/`tools/` runs with the same interpreter.

## Status (2026-10-19)

- Emulated prototype: core + HECI + HAL + filesystem + platform guard + boot
  flow + a service loop, all wired and passing the QEMU test (15 checks).
- HECI now rides the HAL seam: `om_firmware_service_once/`service()` pump packets
  HAL->HECI and HECI->HAL. The model HAL is directional (host->ME / ME->host)
  with host-side hooks (`om_model_host_send/recv`) so a test plays the host.
- Shell commands exercise each subsystem in-guest: `boot` (staged bring-up),
  `run` (autonomous service of a host HOST_START end-to-end through the HAL),
  `platform`, `hal`, `fs`, plus the `frame`/`heci` protocol paths.
- GM45 HAL is still a compiling stub (hardware ops return not-implemented).
- Core runtime COMPLETE: HECI rides the HAL; a single service model
  (`src/service/`, `struct om_service`) is dispatched by `heci.c`; HAL `ticks()`.
- Tier 1 warm-persistence milestone: reboot persistence (boot counter 1→2→3 via
  flashfs, `persist`), autonomous entry `om_firmware_run()`, prototype doc
  (`docs/prototype.md`).
- Dev/production split: `build_openme.py` default builds `main.c` (dev shell);
  `--production` builds `main_prod.c` (NO shell, boot + `om_firmware_run`; ~6 KB
  smaller). A shell must never ship in production.
- Dev shell is sh-STYLE (prompt `openme:/#`): `ls`, `cat FILE`, `echo TEXT > FILE`,
  `rm FILE`, `format` over the flash (files = keys 0-255). It is a small
  freestanding interpreter, NOT real bash/sh (those need an OS the ME must not
  run). The prompt string lives in main.c and run_openme_qemu.py's `until()` +
  heci helpers — keep them in sync if changed.
- Run directly (PowerShell policy may block the .ps1):
  `& 'C:\msys64\ucrt64\bin\python.exe' tools\build_openme.py` then
  `... tools\run_openme_qemu.py --qemu 'qemu-work\qemu-source-clean\build\qemu-system-x86_64.exe' [--interactive]`.
- Tier 1 COMPLETE. Pass 2 done: `tools/run_hostdriver.py` + the `hostdriver`
  build profile (`build_openme.py --hostdriver`, entry `main_hostdrv.c`) + the
  serial/COM2 HAL (`src/hal/serial/serial_hal.c`, `om_hal_serial`). A separate
  Python process drives a real HECI conversation over a TCP-backed COM2 serial
  (4 HECI checks). Build profiles: dev | production | hostdriver | persist.
- Cold process-restart persistence now VERIFIED: `tools/run_persist.py` builds
  `main_persist.c` (`--persist`) and runs two separate QEMU processes over COM2,
  saving/reloading one host NOR file: counter 1 then 2, second boot not formatted.
  This is CRC-checked snapshot export/import, NOT pflash or power-loss durability.
  See `docs/cold-persistence.md` for artifacts/protocol/results. Run directories
  are fresh and retained; never overwrite an earlier test's flash image.
- Current verification: 20 dev QEMU checks, 4 host-driver HECI checks, two cold
  boots, 129 root Python tests (1 expected skip), 39 tool tests. Native tests now
  cover persistence and failed counter writes; boot no longer reports success
  when saving its counter fails.
- Remaining storage realism: write-through backing and power-fail-safe flashfs
  compaction (currently the new sector header precedes copying the records).
- Tier 2 (optional, pure-software): multi-client service registry, watchdog using
  ticks, in-flash event log, fuller S3 power states.
- Tier 3 (BLOCKED): GM45 HAL vs a real image; ARC reverse-engineering.
- Honest limit: this is an EMULATED prototype. Real-silicon boot is gated by the
  undocumented ARC core and is not reachable yet; never report it as achieved.

## Conventions

- Firmware C is freestanding C11, no libc, no allocator; builds must stay clean
  under `-Wall -Wextra -Werror`.
- The QEMU test uses byte-exact assertions — if you change a wire format or shell
  output, update `tools/run_openme_qemu.py` in the same change.
- Never report an emulation result as real ME execution.
