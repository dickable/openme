# Physical flashing workflow

Physical flashing is part of OpenME. The first hardware research family is
Skylake, but no board, chip, programmer, or usable hardware image is selected
yet. The motherboard contains its flash chip; an external programmer is a
separate tool. Internal programming depends on the particular board's access
and recovery arrangements. Selecting `internal` does not guarantee access.

`tools/flash_openme.py` implements backup, offline comparison, and a physical
write/verify/readback path using an installed [flashrom](https://flashrom.org/).
Its device tests currently use mocks; no physical write has been tested.

## Before using hardware

Identify the board and revision, exact chip marking/capacity/voltage, supported
programmer, connection method, and recovery method. Review the full-chip image
for that board, including descriptor, ME region, BIOS, and board-specific data.
One chip is handled per session; split-flash boards need separate plans.

The tool checks sizes, hashes, chip selection, and a fresh read of the original
contents. It cannot independently verify the board identity entered by the
operator or determine whether the candidate can boot. The source-built
`openme-qemu.bin` is a Multiboot executable, **not a full-chip SPI image**.
Do not pad it and use it as one. Hardware execution and authentication/boot
integration have not been implemented by this workflow.

## Commands

These are syntax examples, not values for an unidentified Skylake board.
Replace the uppercase placeholders after identifying the hardware. Run on a
machine with flashrom and the required device permissions. Session directories
must be new; the tool refuses to overwrite an existing session.

```powershell
python tools/flash_openme.py backup --board BOARD-REVISION --programmer PROGRAMMER --chip CHIP --size CAPACITY_BYTES --output hardware-sessions/backup-001
python tools/flash_openme.py plan --backup hardware-sessions/backup-001 --image REVIEWED-FULL-CHIP-IMAGE.bin
```

Backup reads the chip twice, requires byte-for-byte agreement, and records
SHA-256 in `backup.json`. A uniform read is rejected as inconclusive. The
offline plan reports the candidate hash, changed byte count, and offset ranges
with end-exclusive bounds and before/after hashes. At most 256 ranges are
listed; truncation and the full range count are explicit.

Only after reviewing the candidate and recovery arrangement:

```powershell
python tools/flash_openme.py write --backup hardware-sessions/backup-001 --image REVIEWED-FULL-CHIP-IMAGE.bin --output hardware-sessions/write-001 --confirm-board BOARD-REVISION --confirm-sha256 REVIEWED_SHA256 --recovery-note "Describe the specific recovery procedure" --execute
```

The write path snapshots the reviewed candidate, reads the live chip again,
requires it to match the saved baseline, writes with flashrom's verification
enabled, explicitly verifies again, and compares a new readback with the exact
candidate. Commands, output logs, hashes, and the last phase are retained.
The options follow flashrom's [upstream command-line implementation](https://github.com/flashrom/flashrom/blob/main/cli_classic.c).

No automatic retries, forced probe overrides, protection changes, automatic
rollback, or verification suppression are performed. A failure after the write
starts can leave the chip partially programmed; retain the session and follow
the established recovery procedure before resetting or power-cycling. A
successful byte comparison proves programming, not a successful hardware boot.

`hardware-sessions/` is ignored by Git. Do not publish chip backups or serial
numbers with the source.

