# OpenME firmware source

The new source-built OpenME firmware lives here. Existing firmware analysis,
emulation, and protocol research remain under `csme/`.

- `core.c`, `core.h`: freestanding C message processing and service state (portable).
- `mei/heci.c`, `mei/heci.h`: HBM/HECI protocol layer, transport-abstract (portable).
- `hal/hal.h`: hardware abstraction layer — the single seam below the core; one
  implementation per platform (`hal/model/` for emulation, `hal/gm45/` the first
  real-hardware reference port, currently a stub). See
  [../docs/openme-architecture.md](../docs/openme-architecture.md).
- `fs/flashfs.c`, `fs/flashfs.h`: OpenME's own embedded flash filesystem
  (EFFS/MFS-equivalent) — a log-structured key→value store over raw NOR flash.
  `fs/nor_model.c` is the RAM-backed NOR model used for emulation.
- `platform/qemu_x86/`: Multiboot entry, linker layout, and serial command shell
  for the QEMU test target.

Build from the repository root with `python tools/build_openme.py`. Generated
images, maps, disassembly, and build manifests go to `qemu-work/openme-build/`.
QEMU itself remains an external dependency, not part of this source tree.

The shell-free `--persist` profile selects `platform/qemu_x86/main_persist.c`.
Run `python tools/run_persist.py` to verify counter 1 → 2 across independent QEMU
processes using a shared NOR snapshot file. This is not pflash/write-through
storage; see [cold persistence](../docs/cold-persistence.md) for evidence and limits.

The hardware target is the pre-CSME-11, ARC-core ME (generation 6 and earlier);
see [../docs/me6-target.md](../docs/me6-target.md). The current QEMU target is an
abstract development environment, **not** an ME hardware port or a physical SPI
flash image, and it must be reoriented to the ARC/HECI architecture (roadmap
phase 3) to be representative of a real ME. Physical flashing remains a
late-stage, separate activity on permissive owner hardware.

## Current implementation

The QEMU loader hands off in 32-bit protected mode at the Multiboot entry.
`start.S` disables interrupts, clears the direction flag, installs a flat GDT,
loads data/stack selectors, initializes a 16 KiB stack, clears BSS, and calls
`firmware_main`. The guest validates the Multiboot magic and initializes COM1.
The serial shell runs compiled C with no host libc or Python service responses.
Its commands are `help`, `version`, `status`, `hal`, `fs`, `frame HEX`,
`heci HEX`, `heci-poll`, `heci-reset`, and `halt`. `hal` brings up the active
HAL and round-trips one packet through its `send`/`recv` seam; `fs` runs a
format/set/get/update/delete/remount self-test of the flash filesystem. Both
prove their subsystem is linked and callable in the guest.

The core implements one bounded echo service, connection state, synchronous
flow control, suspend/resume, and reset. There is no allocator or host-memory
DMA. Only the QEMU PC UART and test exit port are used; Skylake PCH registers,
Intel HBM/HECI compatibility, interrupts, scheduling, watchdog/power services,
and physical CSME boot integration are not yet implemented.

## Project-defined framed transport

The 16-byte little-endian header follows the existing laboratory frame format:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 2 | Magic `0x4f4d` |
| 2 | 1 | Version `1` |
| 3 | 1 | Flags: request `0`, response `1`, error response `3` |
| 4 | 1 | Opcode |
| 5 | 1 | Status; must be zero in requests |
| 6 | 2 | Reserved, zero |
| 8 | 4 | Nonzero sequence, echoed back |
| 12 | 2 | Payload length, at most 256 |
| 14 | 2 | Reserved, zero |

Opcodes are RESET=1, START=2, ENUMERATE=3, PROPERTIES=4, CONNECT=5,
FLOW_CONTROL=6, DATA=7, DISCONNECT=8, SUSPEND=9, RESUME=10. PROPERTIES and
CONNECT take the ASCII service name `openme.echo` as their payload (no NUL);
DATA uses the current connection. Unlike the older Python adapter's out-of-band
`client` argument, this serial transport carries the service selection in-band.
No Intel MEI compatibility is implied. FLOW_CONTROL returns ASCII `1`: one
synchronous request/response at a time, not four asynchronous model credits.

Invalid headers do not change the core state. Invalid command payloads do not
perform state transitions. Errors preserve the request opcode/sequence where
available; zero/missing sequence falls back to `1`. Response capacity must be
272 bytes. Input and output buffers must not overlap. Overlong serial lines are
discarded through the next newline, so their suffix is never executed.

## Reproducing execution

```powershell
.\tools\launch-openme.ps1 -Test
```

The runner checks complete guest responses, not just startup text. It saves
`qemu-work/openme-build/qemu-test/serial.log`, `execution.log`, and `result.json`.
The QEMU trace includes translated blocks and dispatch addresses; it is not a
retired-instruction count. Builds without a disassembler may print `OBJD-T`
hexadecimal block bytes; `openme.disasm` contains the matching linked-code
disassembly. There is no fallback to the old Python fake device.

Interactive sessions log unique translations only, in
`interactive-translations.log`, so leaving the polling shell open does not
continuously append idle-loop dispatches. Use the bounded automated test for
the execution/dispatch evidence.
