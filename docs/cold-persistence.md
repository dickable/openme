# Cold process-restart persistence — verified 2026-10-19

OpenME's compiled C firmware now retains its boot counter across two **separate
QEMU process lifetimes**. Process 1 mounts an erased NOR image, saves counter 1,
exports the bytes, and exits. Process 2 imports those bytes from the same host
file and saves counter 2 without formatting. The host never writes a counter
record itself.

This is a shell-free **snapshot test profile**, not a pflash controller, a
physical SPI image, Intel firmware execution, or a power-loss durability test.

## Reproduce

From the repository root:

```powershell
& C:/msys64/ucrt64/bin/python.exe tools/run_persist.py
```

Use `--qemu PATH` for another QEMU binary. Each run creates a new directory under
`qemu-work/openme-persist/run-*`. `--output PATH` requires a nonexistent directory;
it never resets an earlier run's flash. QEMU uses loopback TCP solely as the host
transport for COM2, with no emulated NIC. The desktop sandbox required permission
for that local socket; the first sandboxed launch failed before guest boot and
was retained separately in `run-gh124qgi`.

The standalone profile is also available:

```powershell
& C:/msys64/ucrt64/bin/python.exe tools/build_openme.py --persist --output qemu-work/openme-persist-profile-check
```

`main_persist.c` is selected instead of the development shell, production loop,
or host-driver entry. It uses the model HAL and stays powered-off for packet
services throughout this test. COM2 carries test snapshots, not HECI packets.

## Observed result

Verified run: `qemu-work/openme-persist/run-c56dcw7t/`.

| Evidence | First process | Second process |
| --- | --- | --- |
| QEMU PID | 36228 | 2192 |
| Boot count (flash record and COM1) | 1 | 2 |
| Filesystem formatted | 1 | 0 |
| QEMU exit | 33, expected debug-exit | 33, expected debug-exit |
| Firmware services powered | 0 | 0 |

Actual COM1 output:

```text
OpenME persist ready bytes=2048
persist: boot-count=1 formatted=1 net=none powered=0
```

```text
OpenME persist ready bytes=2048
persist: boot-count=2 formatted=0 net=none powered=0
```

- Firmware: 9,384 bytes, entry `0x00100020`, GCC 16.2.0, freestanding i686.
- Firmware SHA-256:
  `359f8fccf250888bcfc532afaf6ef8cfe9ba5718fec376df2c6b64a7a847ff9b`.
- First returned snapshot **and second seed** SHA-256:
  `27e7a32df765a1d7e0ebaa95ffc37f56357cfabcb2dddf8b8c0217e01c146c5a`.
- Final 2,048-byte `flash.bin` SHA-256:
  `f587a4d5e66b06bfdde5506c36e3ae678c4f0ad62a6c7c0296c3b01ceb440f72`.
- The separate `--persist` build reproduced the firmware hash above.

Each `boot-1/` and `boot-2/` folder retains `seed.bin`, `returned.bin`,
`serial.log`, `qemu.stderr.log`, `execution.log`, and `result.json`. The parent
`result.json` contains both exact QEMU commands, PIDs, hashes, outcomes, and the
build manifest. Execution logs show dispatch to `om_nor_load` (`0x00101a6b`),
`om_firmware_boot` (`0x00101b7c`), `flashfs_set` (`0x0010152d`), and `om_nor_save`
(`0x00101a97`) in both processes. There is **no retired-instruction counter**;
translated-block dispatches are not an instruction-retirement count.

## COM2 snapshot protocol (test-only, version 1)

All integers are unsigned little-endian 32-bit values. Payload CRC is standard
CRC32/IEEE (reflected polynomial `0xedb88320`, initial/final XOR `0xffffffff`).
The transfer is bounded to the current 2,048-byte NOR geometry. Firmware has a
4,096-byte staging capacity and refuses a geometry exceeding it.

1. Guest sends `OMP1`, NOR length.
2. Host sends `OMI1`, seed length, seed CRC32. Guest checks extent and sends ACK
   byte `06`. Host sends 16-byte chunks, waiting for an ACK after each chunk.
3. Only after validating the entire seed CRC does firmware restore the NOR
   model. It refuses an unmountable, non-erased seed, boots, and saves the model.
4. Guest sends `OMO1`, output length, CRC32, boot count, formatted flag. Host
   validates header bounds and ACKs. Guest sends chunks, each ACKed by the host.
5. Host verifies CRC32 and independently parses the flashfs record/CRC16, checks
   the COM1 result and successful process exit, and checks execution evidence.
   Only then does it flush and atomically replace its shared `flash.bin`.

Chunk acknowledgements prevent UART input bursts from depending on timing.
They acknowledge receipt, not durability. A 20-second host-side deadline bounds
each QEMU run; guest UART polling itself has no hardware timer timeout. Before
debug-exit, the guest waits for both UART transmitters to empty.

## Regression results

Python means `C:/msys64/ucrt64/bin/python.exe` on the tested host. Root/tool suites
used `TEMP`, `TMP`, and `TMPDIR` pointing to `qemu-work/test-temp` because the MSYS2
runtime cannot use the desktop sandbox's default temporary directory reliably.

| Exact test/build command | Result |
| --- | --- |
| `python tools/run_persist.py` | PASS: two completed processes; counter 1 → 2 |
| `.\tools\launch-openme.ps1 -Test` | PASS: 20 QEMU checks, 19 framed exchanges, 27 HBM submissions / 19 replies |
| `python tools/run_hostdriver.py` | PASS: 4 HECI checks over separate-process COM2 |
| `python -m unittest discover -s . -p 'test*.py'` | 129 tests, OK; 1 expected skip |
| `python -m unittest discover -s tools -p 'test*.py'` | 39 tests, OK |
| `python tools/verify_lab.py` | PASS: historical synthetic lab, separate from this firmware result |
| `python tools/build_openme.py --production --output qemu-work/openme-production-check` | PASS: 8,264-byte shell-free image, `-Werror` |
| `python tools/build_openme.py --persist --output qemu-work/openme-persist-profile-check` | PASS: reproduced persistence image |
| `openme-pci-test.exe -p /openme/mmio-contract` | PASS: 1 native QTest, using the environment documented in source-firmware-milestone.md |

New native regressions cover snapshot extents/canaries, NOR program restrictions,
restoring saved bytes, and failed counter writes, CRC errors, invalid lengths,
and overflow. Boot previously ignored `flashfs_set` failures; it now fails the
boot, leaves `boot_count` unreported, and closes the service power gate.
Python regressions cover fragmented stream reads, bounded lengths, bad CRCs,
wrong counter reports, disconnection/deadline handling, and atomic-commit failure
without replacing the previous file.

## Changed files for this step

- `src/platform/qemu_x86/main_persist.c`
- `src/firmware.c`
- `tools/build_openme.py`, `tools/run_persist.py`, `tools/test_run_persist.py`
- `csme/tests/test_openme_persistence.c`, `csme/tests/test_source_firmware.py`
- `CLAUDE.md`, `docs/prototype.md`, this report, `src/README.md`,
  `tools/README.md`, `csme/tests/README.md`

The existing `om_nor_load/save/total` implementation was reused unchanged.
No original/vendor firmware or physical flash was modified.

## Remaining boundary

Changes become host-persistent only after successful snapshot export and
validation. Killing QEMU before that point loses its unsaved RAM-backed changes.
This is not write-through storage or evidence of atomic filesystem updates under
power interruption. Existing flashfs compaction publishes a new sector header
before copying all records; power-fail-safe commit ordering and fault injection
remain concrete follow-up work. The generic boot also still auto-formats an
unmountable store; this test entry guards non-erased snapshots separately.

The hardware HAL remains a stub. This test establishes process-restart
persistence for OpenME's own QEMU firmware, not real ME compatibility or boot.
