# OpenME emulated prototype

This describes the current, working prototype. It is an **emulated** prototype:
it boots and runs under QEMU as a freestanding firmware and is exercised by an
automated test. It does **not** run on real ME silicon (that is gated by the
undocumented ARC core — see [me6-target.md](me6-target.md)); no emulation result
is reported as real ME execution.

## What it does

On the QEMU target, OpenME:

1. boots (Multiboot) into freestanding C,
2. runs a staged bring-up (`om_firmware_boot`): platform guard → HAL → filesystem
   → persistent boot counter → HECI, refusing to proceed on unsupported hardware,
3. stays **dormant** until powered on (S0),
4. once powered on, **services a host** over the HAL through a pluggable service,
5. persists config (the boot counter) across reboots in its flash filesystem.

## Subsystems

| Area | Files | Role |
| --- | --- | --- |
| Core protocol | `src/core.c` | framed-v1 message/service state machine |
| HECI/HBM | `src/mei/heci.c` | host↔ME protocol; dispatches to a service |
| Service model | `src/service/` | `struct om_service`; `om_service_echo` |
| HAL | `src/hal/` | local transport + bring-up + ticks; `model` (emulation), `gm45` (stub) |
| Filesystem | `src/fs/` | EFFS/MFS-equivalent over a NOR model |
| Platform guard | `src/platform/support.c` | supported-hardware registry; warn/refuse |
| Boot + loop | `src/firmware.c` | `om_firmware_boot`, `_service(_once)`, `_power`, `_run` |
| Capabilities | `src/capabilities.h` | the no-network invariant |

## Trust properties (both structural, both asserted in QEMU)

- **No network, ever.** No network stack, no AMT, no out-of-band management
  (`OPENME_CAP_NETWORK = 0`). The HAL exposes only a local host↔ME transport, so
  the firmware has no mechanism to reach a network. Boot reports `net=none`.
- **Dormant by default.** The firmware services nothing until the system is
  powered on (S0); unlike the stock ME it does nothing in standby/off.

## Dev vs production build

There are four profiles, selected by `build_openme.py`:

- **dev** (default) — `main.c`, with the interactive serial shell and all the
  debug/self-test commands. This is the test target.
- **production** — `build_openme.py --production` uses `main_prod.c`, which has
  **no shell at all**: it boots and enters the autonomous service loop. The shell
  code is not compiled or linked in (the production image is ~6 KB smaller). A
  shell is a debug surface and must never ship in a real ME image.
- **hostdriver** (`--hostdriver`) — shell-free autonomous service over COM2.
- **persist** (`--persist`) — shell-free NOR snapshot import, boot, export, and
  exit; used by the cold process-restart test, not a production storage driver.

## Build and test

```powershell
# Directly (works regardless of PowerShell execution policy):
& 'C:\msys64\ucrt64\bin\python.exe' tools\build_openme.py
& 'C:\msys64\ucrt64\bin\python.exe' tools\run_openme_qemu.py --qemu 'qemu-work\qemu-source-clean\build\qemu-system-x86_64.exe'
# Interactive shell: add --interactive to the run command.
# Production image: add --production to the build command.

# Or via the launcher (if script execution is allowed):
.\tools\launch-openme.ps1 -Test   # build + run the full QEMU test suite
.\tools\launch-openme.ps1         # build + open the interactive serial shell
```

The test suite (`tools/run_openme_qemu.py`) boots the firmware under QEMU and
asserts byte-exact behavior across 20 checks, including the framed and HBM
protocol paths and the subsystem self-tests below. Builds are clean under
`-Wall -Wextra -Werror`; no libc, no allocator.

## Shell commands (what each verifies)

| Command | Verifies |
| --- | --- |
| `boot` | staged bring-up; reports `net=none result=ok` |
| `run` | autonomous service of a host `HOST_START` end-to-end through the HAL |
| `convo` | full host conversation through a transform service (dispatch proof) |
| `gate` | dormant-until-powered-on (message ignored while off, serviced when on) |
| `persist` | boot counter survives reboot on retained flash (1→2→3) |
| `platform` | supported-platform guard |
| `hal` | HAL seam, both directions |
| `fs` | filesystem format/set/get/update/delete/remount |
| `time` | HAL timebase advances |
| `frame HEX` / `heci HEX` / `heci-poll` | protocol layers directly |
| `ls` | list files (keys) in the emulated flash, with sizes |
| `cat FILE` | print a file's contents |
| `echo TEXT > FILE` | write a file (sh-style) |
| `rm FILE` | delete a file |
| `format` | wipe the filesystem |

The dev shell presents an sh-*style* interface (prompt `openme:/#`, `ls`/`cat`/
`echo`/`rm`). It is a small freestanding interpreter, not a real bash/sh — those
need an OS, which the ME deliberately does not run. Files are flash keys (0–255);
the commands operate on the same flash the firmware uses, so after `boot`/`persist`
an `ls` shows the firmware's own boot counter (file `0`).

## Host-driver test (separate process over COM2)

`run_hostdriver.py` builds the shell-free **hostdriver** image (serial/COM2 HAL)
and drives it from a separate Python process over a TCP-backed second serial,
running a real HECI conversation (HOST_START → CONNECT → grant → DATA echo):

```powershell
& 'C:\msys64\ucrt64\bin\python.exe' tools\run_hostdriver.py --qemu 'qemu-work\qemu-source-clean\build\qemu-system-x86_64.exe'
```

This is the true two-party test: `om_firmware_run` services COM2, the external
driver plays the host. The in-guest shell commands (`run`/`convo`) remain as the
fast self-tests.

## Cold process-restart persistence

```powershell
& 'C:\msys64\ucrt64\bin\python.exe' tools\run_persist.py
```

Verified: two independent QEMU processes, sharing a host NOR snapshot file,
report and persist boot counts **1 then 2**. The second boot mounts without
formatting. CRC-checked snapshots, serial logs, execution traces, and manifests
are retained in a fresh `qemu-work/openme-persist/run-*` directory each time.
See [cold-persistence.md](cold-persistence.md) for the exact verified artifacts,
commands, protocol, and failure-path regressions.

This is a COM2 snapshot test, **not pflash**: the NOR remains RAM-backed while
the guest runs and exports only at the successful end of the test.

## Honest limits / what's next

- **Power-loss durability** — snapshot restart works, but killing QEMU before
  export loses unsaved writes. Write-through backing and power-fail-safe flashfs
  compaction are not implemented or validated.
- **Real silicon** — blocked on the ARC black box; the `gm45` HAL is a stub.
