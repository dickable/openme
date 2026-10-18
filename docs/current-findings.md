# Current findings

This is the preserved-image execution record for the OpenME project. The
original firmware files remain local and ignored. The working copy is currently
byte-identical to the original. Strict execution decodes the real `rbe` module
but stops before fetch because cryptographic admission is unknown. An explicit
emulator-only admission experiment executes the real bytes until the first
unmapped platform write. No bytes have been flashed or uploaded.

## Research target

The working target is one Lenovo ThinkPad T460-class platform: machine type
20FM, non-vPro, with a reference Core i5-6200U Skylake-U configuration. The
reference software baseline is Lenovo BIOS 1.45 (`R06ET71W`) and ECP 1.11
(`R06HT31W`). These references do not prove the versions installed on a future
machine. Board revision, SPI part, descriptor permissions, ME version, device
configuration, and Boot Guard policy remain unverified.

The filename `Lenovo T460 NM-A581.bin` suggests the supplied image is from a
T460 board, but board identity has not been independently verified.

## Local artifacts

The BIOS package is an ISO9660 image with volume ID `R06ET71W`, size
22,392,832 bytes, and SHA-256:

`a6ce3edd3504bfa8fdc98142640df6bf97a62de1135abe423f47ebf2656f6cbd`

It was inspected read-only and was not mounted, extracted, executed, or
flashed. Its metadata is recorded in
`firmware-samples/t460-bios-iso.metadata.json`.

The local SPI artifacts are:

| File | Size | SHA-256 |
|---|---:|---|
| `Lenovo T460 NM-A581.bin` | 16 MiB | `080638a445737941336a79db056e64c0090241f3ac52c460fb5e3c0b20a20e2f` |
| `T460 ECROM.bin` | 256 KiB | `64c10d1c7fce9f6bc43c7f9419371249f3a5a7c32a8aff6dc8514bdd7c687162` |

Both remain under the ignored `downloaded-firmware/` directory.

## SPI descriptor findings

The 16 MiB image is structurally coherent as a descriptor-based SPI image:

- Descriptor signature: offset `0x10`
- Region table: offset `0x40`
- `FLMAP0`: `0x00040003`
- `FLMAP1`: `0x42100208`
- `FLMAP2`: `0x00310330`

| Region | Offset | Size | SHA-256 |
|---|---:|---:|---|
| Flash Descriptor | `0x000000` | `0x001000` | `fa77943056e74b57e6943bcef9d5e90b12d4a3e6e9ff5c10320f2cc1209380d4` |
| GbE | `0x001000` | `0x002000` | `117c9e86d412e4d53d1ac2a3a5fa6f7a008a2813cdfc48931c6bd429eeec60a7` |
| Intel ME | `0x003000` | `0x6FD000` | `1e04d1e99ba0de64cdbebaa085e68f54fcccc7dc38705f56ac0e8357c29b80b5` |
| BIOS | `0x700000` | `0x900000` | `b749986bbf3b1d381622e0232602aa1b77b0310b79d7e46a3ad37810df7d0a74` |

## ME partition findings

The ME region contains an `$FPT` at ME-relative offset `0x10`, absolute image
offset `0x3010`, with 13 partition records:

| Partition | ME-relative offset | Size |
|---|---:|---:|
| FTPR | `0x001000` | `0x12F000` |
| FTUP | `0x272000` | `0x38E000` |
| DLMP | `0x000000` | `0x000000` |
| PSVN | `0x000E00` | `0x000200` |
| IVBP | `0x26E000` | `0x004000` |
| MFS | `0x130000` | `0x13E000` |
| NFTP | `0x272000` | `0x30B000` |
| ROMB | `0x000000` | `0x000000` |
| WCOD | `0x57D000` | `0x080000` |
| LOCL | `0x5FD000` | `0x003000` |
| FLOG | `0x600000` | `0x001000` |
| UTOK | `0x601000` | `0x002000` |
| ISHC | `0x000000` | `0x000000` |

Repeated `$MN2` candidates were found at ME-relative offsets `0x1494`,
`0x2725B4`, `0x57D104`, and `0x5FD0D4`. Their observed 16-bit tuples are,
respectively, `[11, 0, 0, 1198]`, `[11, 0, 0, 1198]`, `[11, 0, 0, 1198]`,
and `[11, 0, 0, 1175]`. These are undocumented candidate fields, not a
verified CSME marketing version. A literal `11.8` string was not found in the
ME region.

## FTPR CPD findings

The FTPR partition begins with a `$CPD/` directory. The directory contains 47
entries and ends at FTPR-relative offset `0x478`; all described ranges fit
inside the `0x12F000` FTPR partition.

The observed names include the manifest `FTPRFTPR.man`, runtime components
`rbe`, `kernel`, `syslib`, `bup`, `pm`, `syncman`, `vfs`, `evtdisp`, `loadmgr`,
`busdrv`, `gpio`, `prtc`, `policy`, `crypto`, `heci`, `storage`, `pmdrv`,
`maestro`, `fpf`, `hci`, `fwupdate`, `ptt`, and `touch_fw`, plus their `.met`
companions where present. The names are inventory labels only; they do not
prove undocumented internal behavior or public protocol compatibility.

The complete names, offsets, sizes, and packed flags are recorded in
`firmware-samples/t460-ftpr-cpd.metadata.json`. The parser also computes
range hashes without writing extracted modules.

## Software model findings

The local QEMU build is version 11.1.50 with the project label
`openme-local`. The OpenME device is deliberately a project-defined test
device, not an Intel device definition:

- Test-only PCI identity `0x1234:0x4D45`
- One small MMIO BAR
- Bounded payload window: 16-byte frame header plus 256-byte payload
- No DMA, firmware loading, hardware access, network access, or security-bypass behavior
- Deterministic state machine with reset, start, enumeration, connect, data,
  suspend, and resume behaviors
- Project-defined clients `openme.control` and `openme.echo`
- Explicit queued transport with capacity eight and deterministic service steps

This current interface is not Intel HECI/MEI and makes no compatibility claim.
It is the lowest-fidelity controlled test surface for host-side behavior,
traces, and QEMU integration. That is a statement about the current prototype,
not a conclusion that a more faithful ME emulation is impossible.

## Safety and unresolved questions

- The image has not been proven to match a particular physical board.
- Exact SPI chip accessibility and recovery points are unknown.
- Descriptor write permissions are unknown.
- The installed ME/CSME marketing version is not asserted by current metadata.
- Boot Guard policy and platform authentication details are unknown.
- The ECROM has been hashed but not behaviorally analyzed.
- No conclusion about a universal Skylake implementation is justified.
- No hardware modification or flashing has occurred.

## Current next step

The reproducible `tools/analyze_real_rbe.py` report now traces the caller at
`0x40216` into `0x40000` and correlates the exact first fault:
`mov dword ptr [eax-0x4],ecx` at `0x4001d`, a 4-byte write of
`0x06041288` to `0x06040000`. The source value comes from the decoded module
word at `0x43000` (`rbe` offset `0x3000`), which is in decoded capacity but
outside the valid `0x29c6`-byte code extent.

The address is now classified as an evidence-derived global/BSS window for the
emulator: the real code stores `0x06041288` there, later uses it as a context
pointer, and embeds `0x06047004`, exactly `0x7004` bytes above the base and
equal to the metadata BSS size. Only that bounded window is mapped; the
unmapped-write policy remains unchanged elsewhere. The real-image run advanced
to 40 instructions / 106 instruction bytes and then reached an external fetch
at `0x103d` from the call at `0x419bd`. The next blocker is the missing
target-generation ME ROM/library implementation at that address. No synthetic
stub or successful boot claim was added.
