# Tools

This directory contains utilities for parsing, hashing, firmware builds, QEMU
tests, and physical flashing. Image-analysis tools keep their stated access
policies. Hardware operations are separate, explicit commands in
`flash_openme.py`; the normal build and QEMU launcher do not access hardware.

- `build_openme.py`: build the new C firmware under `src/` and record its hash,
  entry, load bounds, source hashes, compiler commands, map, and disassembly.
- `run_openme_qemu.py`: interact with compiled firmware in QEMU; save a serial
  transcript, translation/TB-dispatch trace, and JSON test result.
- `launch-openme.ps1`: open a visible PowerShell window, build, and run the QEMU
  shell; add `-InPlace` to use the current terminal or `-Test` for automated tests.
- `flash_openme.py`: independent chip backups, offline image comparison, and
  explicitly confirmed flashrom write/verify/readback. See `hardware/README.md`.

`inspect_iso.py` reads ISO9660 metadata and root-directory names without mounting, extracting, executing, or modifying the image.

`parsers/inspect_me.py` reports the Flash Descriptor-selected ME region and its
Firmware Partition Table boundaries. It records structure and hashes only; it
does not claim a CSME marketing version from undocumented binary fields.

The ISO inspector also reports file counts, extension counts, and firmware-like
candidate names. Candidate classification is based only on directory metadata;
the tool does not extract or execute candidate files.

`audit_publication.py` is a read-only pre-publication check. It examines only
directory names, file names, and file sizes, and flags likely firmware packages,
raw dumps, and large files. It does not open candidate files, inspect their
contents, modify Git metadata, or upload anything. Review every finding before
publishing; a clean result is not proof that a repository contains no
proprietary material.

`compare_traces.py` compares two JSON event traces for the software model. It
accepts either a top-level event list or an object containing `trace`/`events`,
ignores capture sequence and timing fields, and reports deterministic field-level
mismatches. It is read-only and returns exit status 0 for a match, 1 for a
mismatch, and 2 for invalid input.

`analyze_real_rbe.py` decodes the preserved ME11 `rbe` bytes through the same
bounded CPD/Huffman/metadata path as the real-byte runtime. It reports the
caller around `0x40216`, bounded control/data flow, every little-endian
reference to `0x06040000` and `0x06041288`, nearby pointer-like values, and
the meloader mapping evidence. It never maps the unresolved target and never
executes or modifies the image:

```powershell
& C:\msys64\ucrt64\bin\python.exe tools\analyze_real_rbe.py `
  "working-copies\Lenovo T460 NM-A581.bin" `
  --trace qemu-work\traces\fault-layout-final.jsonl `
  --output qemu-work\traces\real-rbe-analysis.json
```

`run_model_trace.py` records a fixed fake-model scenario, and
`replay_model_trace.py` replays the host-side requests from that trace and
checks that the model produces the same deterministic events. Both operate on
JSON and have no hardware or network behavior.

The project also tracks [spispy](https://github.com/osresearch/spispy) as a future hardware/emulation reference. It is an FPGA-based SPI flash emulator and monitor, not a parser for Intel ME firmware images; its documented limitations and voltage requirements must be reviewed before any hardware use.

## Source-firmware cold persistence

`python tools/run_persist.py` builds the `--persist` profile and runs two separate
QEMU processes sharing a host NOR snapshot. It checks counter 1 → 2, snapshot
CRCs, persisted records, process exit, and execution evidence. Each run retains
its artifacts in a new `qemu-work/openme-persist/run-*` directory. It uses only a
loopback COM2 test channel; no physical chip is touched. See
[cold-persistence.md](../docs/cold-persistence.md). This is not a pflash driver.

## Visible real-image attempt

From the project root, run:

```powershell
 .\tools\launch-real-me-execution.ps1
```

This opens a separate PowerShell window and runs the bounded real-image
execution attempt against the preserved T460 SPI image. It prints the image
hash, discovered format, entry-point decision, instruction/MMIO counts, and
the trace path. If the image cannot supply a verified entry point or required
ROM/library dependency, it stops before fetch and reports that fact; it never
falls back to the synthetic model and never modifies the dump. To run the
explicit emulator-only admission-gate experiment, use:

```powershell
.\tools\launch-real-me-execution.ps1 -AllowEmulationAuthBypass
```

That option does not accept a cryptographic signature and has no physical
hardware effect. It is considered successful only when the trace contains
actual instruction events from the decoded module.
