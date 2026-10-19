# Source-built OpenME milestone — 2026-10-18

The C firmware in `src/` boots on QEMU's PC test machine and responds through
its serial command shell. This is OpenME's own compiled code, not an additional
Intel ME11 execution milestone or a Skylake CSME hardware boot.

## Artifact and execution evidence

- Binary: `qemu-work/openme-build/openme-qemu.bin`, 2,336 bytes.
- SHA-256: `c6727a48169195ba5a06ce8e6c8def50f16ad21c3b35c21490b6b4f2e316c759`.
- Compiler: MSYS2 UCRT64 GCC 16.2.0; guest target is freestanding i686/x86-32.
- Load base `0x00100000`, entry `0x00100020`, load end `0x00100920`,
  BSS end `0x00104da0`. Load extent and BSS capacity are separately validated.
- First entry instructions: `cli`, `cld`, `mov esi,eax`,
  `lgdt [0x00100080]`, far jump to selector `0x08`, offset `0x00100032`.
- The recorded run passed six integration checks and 19 complete frame
  exchanges, including a 256-byte binary payload. The trace recorded dispatch
  at 176 distinct firmware block-start addresses, including the entry.
- There is no retired-instruction counter. QEMU's translated-block/dispatch
  log is not a complete instruction-retirement trace; do not equate the address
  count or disassembly length with an instruction execution count.
- Guest `halt` wrote `0x10` to QEMU's test exit device, returning process status
  33 as expected. The wrapper reports success as exit 0.

The complete QEMU command, image identity, checks, and dispatched block starts
are saved in `qemu-work/openme-build/qemu-test/result.json`. Guest serial output
is in `serial.log`, and execution evidence in `execution.log` alongside it.
`openme.map`, `openme.disasm`, and `manifest.json` are in the build directory.
The manifest includes source hashes and every compile/link command.

A second build in `qemu-work/openme-repro-build/` produced the same binary hash.
This checks reproducibility with the installed toolchain, not across compilers.

## Commands and observed results

Commands run from the repository root; Python below is
`C:/msys64/ucrt64/bin/python.exe` on the tested Windows host.

| Command | Result |
| --- | --- |
| `.\tools\launch-openme.ps1 -Test` | Build and QEMU integration PASS; 6 checks / 19 exchanges |
| `python -m unittest discover -s . -p 'test*.py'` | 127 tests, OK; 1 expected skip |
| `python -m unittest discover -s tools -p 'test*.py'` | 32 tests, OK |
| `python tools/verify_lab.py` | PASS, including the older synthetic lab checks |
| `python tools/build_openme.py --output qemu-work/openme-repro-build` | Same binary hash |
| `python -m py_compile tools/build_openme.py tools/run_openme_qemu.py tools/flash_openme.py tools/verify_lab.py` | PASS |
| `git diff --check` | PASS |

The expected skip is the Unicorn-unavailable test: Unicorn is installed. Both
native C harnesses are compiled and run by the root suite; the new core harness
also exercises 10,000 deterministic malformed inputs. The flashing tests mock
all programmer operations. No real chip was written.

The older native OpenME PCI QTest also passes, using this environment and
command (Windows sandbox socket restrictions required running this outside
the sandbox):

```powershell
$env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH
$env:QTEST_QEMU_BINARY = (Resolve-Path 'qemu-work/qemu-source-clean/build/qemu-system-x86_64.exe').Path
$env:TEMP = (Resolve-Path '.qtest-tmp').Path
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
& ./qemu-work/qemu-source-clean/build/tests/qtest/openme-pci-test.exe -p /openme/mmio-contract
```

Result: `ok 1 /openme/mmio-contract`, exit 0. QEMU was rebuilt at commit
`a19f59a72d96056d9a8f48cf6c77f5787491e414` with the local experimental patch.
This is OpenME's relevant native QTest, not a run of the entire upstream QEMU
test matrix. The patch was checked against the modified checkout with:

```powershell
git -C qemu-work/qemu-source-clean apply --check --reverse --ignore-space-change C:/Users/peyton/Documents/openme/csme/qemu/openme-qemu.patch
```

`--ignore-space-change` accommodates the existing CRLF checkout. The patch is
kept in the source repository; the QEMU tree and binaries remain ignored.

## Fixes found during implementation

The MinGW PE intermediate gave `.text` an RVA of zero, which BFD extracted at
zero instead of the guest address. A zero PE image base plus the explicit
linker addresses fixes extraction; header bounds are still checked strictly.

Windows QEMU's redirected stdio discards CR and can drop bytes when the UART
FIFO is full. The test now sends LF and waits for the firmware echo for each
input byte, rather than assuming arbitrary input bursts are lossless.

The lab verifier used full package names to look up a dictionary keyed by short
module names. It now runs its contract checks correctly, with regressions for
both successful and missing imports.

The older native PCI model's 272-byte TX buffer overlapped RX by 16 bytes.
Revision `0x00010001` relocates TX/RX to `0x400`/`0x600`. The expanded regression
also caught byte accesses widened to four bytes at the buffer end, and FAULT
states incorrectly advertising SPI/MEI online. Those are corrected in the
local QEMU patch; the same fault-status issue is fixed in the C scaffold.

## Changed files for this implementation

New firmware and tooling:

- `src/core.c`, `src/core.h`, `src/README.md`
- `src/platform/qemu_x86/start.S`, `main.c`, `link.ld`
- `tools/build_openme.py`, `tools/run_openme_qemu.py`, `tools/launch-openme.ps1`
- `tools/flash_openme.py`
- `csme/tests/test_openme_core.c`, `test_source_firmware.py`, `test_flash_workflow.py`

Existing code and integration:

- `csme/bootloader/openme_me_platform.c`
- `csme/tests/test_openme_me_platform.c`
- `tools/verify_lab.py`, `tools/test_verify_lab.py`
- `csme/qemu/openme-qemu.patch`, `openme-qemu-apply.md`, `README.md`
- Local ignored QEMU files: `hw/misc/openme-pci.c`, `tests/qtest/openme-pci-test.c`.
  The old test executable was retained as `openme-pci-test.pre-mmio-fix.exe`.

Documentation/configuration:

- `.gitignore`, `README.md`, `tools/README.md`, `csme/tests/README.md`
- `docs/project-scope.md`, `docs/safety-and-recovery.md`, `docs/target-platform.md`
- `hardware/README.md`, this report

Other pre-existing dirty research/parser files were preserved. The T460
baseline and working copy still both hash to
`080638a445737941336a79db056e64c0090241f3ac52c460fb5e3c0b20a20e2f`.
No proprietary firmware patches or additional Intel instruction execution are
claimed in this milestone.

## Next concrete gap

The C core is a small development firmware with one project-defined service.
It does not yet implement Intel HBM/HECI, a Skylake PCH hardware backend,
interrupts/scheduling, platform power/watchdog behavior, or the physical CSME
boot chain. The next software step is an evidence-backed C transport backend
with conformance tests against the existing MEI/HBM research. Physical work
additionally needs an identified board/chip, access and recovery arrangements,
and a compatible full-chip image; the flashing wrapper cannot supply these.
