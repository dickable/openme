# Boot-dependency report

## Exact purpose

This report is a read-only inventory of the metadata needed to discuss a
possible T460 boot-dependency model. It answers:

- which SPI and ME partitions are identified;
- which FTPR CPD entries are present and where their declared ranges lie; and
- which names may be relevant to host-facing HECI/MEI, storage, and power-
  management discussions.

It does **not** establish that the dump is authentic, that it belongs to a
particular T460 board, that any module is safe to run, or that any module
implements a documented public interface. It is a dependency map, not a boot
plan, loader, emulator input, compatibility claim, or execution approval.

The current report is based on the checked-in metadata records:

- `firmware-samples/t460-spi-dump.metadata.json`
- `firmware-samples/t460-ftpr-cpd.metadata.json`

The original firmware files are not part of this report and must remain
outside version control.

## Read-only guarantees

The report procedure is metadata-only and must preserve these guarantees:

1. The source image is opened only for bounded structural inspection and
   hashing. It is never written, renamed, truncated, patched, or otherwise
   modified.
2. The procedure does not mount, boot, load, interpret, JIT-translate, or
   execute firmware code or a firmware-defined entry point.
3. CPD entries are recorded as names, declared offsets, sizes, packed flags,
   and optional hashes. No module is extracted, reconstructed, or executed.
4. Unknown, encrypted, signed, compressed, or opaque fields remain unknown.
   The report must not infer undocumented security or version semantics from
   a field shape, a module name, or a hash.
5. The procedure has no flash, SPI-write, NVRAM-write, recovery-media, or
   hardware-control path. It must not contact production systems or upload
   source material.
6. A report output is a new, separate metadata artifact. It must never be
   written over the source image or over an original acquisition record.

These guarantees do not authorize execution. They only define the safe
endpoint for this report.

## How to run the report

### Preferred current operation: read the existing metadata

For the current T460 record, inspect the two metadata files above. Do not open
the original dump merely to reproduce facts that are already recorded. A
read-only PowerShell review is:

```powershell
Get-Content .\firmware-samples\t460-spi-dump.metadata.json
Get-Content .\firmware-samples\t460-ftpr-cpd.metadata.json
```

This operation reads JSON metadata only.

### Reproducible parser run, only when separately authorized

If a future review specifically authorizes a fresh read-only parse, use an
original, preserved input path and write JSON results to a separate report
directory. The parser commands are positional and must be run one at a time:

```powershell
$image = 'D:\preserved-input\Lenovo T460 NM-A581.bin'
$out = 'D:\read-only-report\2026-10-18'
New-Item -ItemType Directory -Force $out | Out-Null

python .\parsers\inspect_ifd.py $image |
  Set-Content (Join-Path $out 'ifd.json')
python .\parsers\inspect_me.py $image |
  Set-Content (Join-Path $out 'me.json')
python .\parsers\inspect_cpd.py $image |
  Set-Content (Join-Path $out 'cpd.json')
python .\parsers\inspect_cpd_manifest.py $image |
  Set-Content (Join-Path $out 'cpd-manifest.json')
```

The commands above describe the approved parser boundary; they are not an
instruction to run against a real dump during ordinary development. Before
any fresh run, confirm that the input is preserved, the output directory is
separate, and the run is limited to read-only parsing. Stop if a parser would
need to extract, load, emulate, execute, modify, or write the input.

The parser output is not a unified boot report unless a reviewer records the
four outputs together with the source hash and the tool revision. A clean
parser result is not proof of authenticity, platform identity, or execution
safety.

## Current T460 metadata and interpretation

### Container and ME boundaries

The recorded artifact is a coherent 16 MiB descriptor-based SPI image. The
descriptor signature is at `0x10`, the region table is at `0x40`, and the
descriptor selects an Intel ME region beginning at image offset `0x003000`
with size `0x6FD000`. The ME region contains an `$FPT` at ME-relative offset
`0x0010`, absolute image offset `0x003010`, with 13 partition records.

The filename suggests a Lenovo T460 NM-A581 source, but board identity has not
been independently verified. The repeated MN2 candidate tuples are
`[11, 0, 0, 1198]` at three locations and `[11, 0, 0, 1175]` at one location.
They are undocumented candidate fields. They do not prove a CSME marketing
version, and this report must not label the image “CSME 11.8” on that basis.

### FTPR

The FTPR record begins at ME-relative offset `0x001000` and has size
`0x12F000`; its corresponding absolute image offset is `0x004000`. The
partition begins with a `$CPD/` directory. The CPD directory ends at
FTPR-relative offset `0x478` and contains 47 entries.

FTPR is therefore a declared container boundary and a useful place to
inventory names and ranges. It is not, by itself, proof that the contents are
complete, authentic, executable in an emulator, compatible with a T460 host,
or acceptable to the platform's security policy.

### MFS

The MFS record begins at ME-relative offset `0x130000` and has size
`0x13E000`. This is a partition-table fact. The label and boundary do not
prove the contents, schema, persistence behavior, provisioning state, or
relationship to a particular boot path. No MFS files, records, secrets, or
keys are extracted by this report.

### CPD modules

The CPD records contain inventory labels, low-24-bit offsets within FTPR,
sizes, and the high-byte packed flags. The field note in the metadata records
explicitly treats this as observed layout, not an assignment of undocumented
flag semantics. The names are dependency candidates only; they are not a
call graph or proof of load order.

The names relevant to the current boot-dependency discussion are:

| CPD entry | FTPR-relative offset | Declared size | Recorded flag | Safe interpretation |
| --- | ---: | ---: | ---: | --- |
| `heci` | `0x09EE40` | `0x00407D` | `0x00` | A component inventory label associated with the HECI name; no HECI/MEI compatibility claim follows. |
| `storage` | `0x0A2EC0` | `0x009000` | `0x02` | A component inventory label associated with storage; no MFS schema or persistence behavior follows. |
| `pm` | `0x04E780` | `0x006000` | `0x02` | A component inventory label associated with power management; no power-state behavior follows. |
| `pmdrv` | `0x0A9780` | `0x004000` | `0x02` | A second power-management-related inventory label; no driver contract follows. |

The report also records `.met` companions and other names such as `kernel`,
`bup`, `busdrv`, `gpio`, `policy`, `crypto`, `hci`, and `fwupdate`. Those
names can guide a later metadata question, but they do not establish a
dependency order, an instruction set, a public protocol, or a safe execution
surface.

### HECI, storage, and PM conclusions

- `heci` is evidence only that an entry with that name is listed in FTPR. It
  does not establish Intel HECI/MEI register behavior, client GUIDs, HBM
  behavior, interrupt behavior, or host-driver compatibility.
- `storage` is evidence only that an entry with that name and declared range
  is listed. It does not establish access to MFS, a storage format, a write
  policy, or a persistence dependency.
- `pm` and `pmdrv` are labels that may be relevant to power-management
  modeling. They do not establish reset sequencing, sleep-state support,
  clock or rail control, or the behavior of a physical T460.

The safe implementation consequence is to model these as synthetic,
project-defined dependencies until independently documented host behavior or
controlled traces justify a narrower claim. No real CPD range may be mapped
into an emulator under this report.

## Report status

This report is a preflight dependency record, not an execution result. It
does not establish a verified reset vector, entry point, ROM/library image, or
authentication decision for the preserved dump. The executable attempt is
implemented separately in `csme/runtime/real_image_attempt.py`; it must stop
before instruction fetch when those dependencies are unavailable. No hardware
flashing or security-check bypass is permitted.
