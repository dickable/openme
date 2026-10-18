# Real-image execution attempt

The visible launcher is:

```powershell
.\tools\launch-real-me-execution.ps1
```

The launcher uses the preserved working copy at
`working-copies/Lenovo T460 NM-A581.bin`, verifies its SHA-256, labels the
mode `REAL FIRMWARE INSTRUCTION EXECUTION`, and writes a JSONL trace under
`qemu-work/traces/`. It never flashes hardware or modifies either image.

The execution path now has an image-specific profile and a bounded loader. It
identifies the descriptor/FPT/FTPR/CPD container, treats CPD offset-attribute
bit 25 as ME11 Huffman storage, obtains stored/uncompressed lengths from the
module metadata, and verifies Huffman output before execution. The x86-32
Unicorn backend maps the preserved SPI window, SRAM/DRAM, and the defined
PCH/MEI ranges through the bounded host-platform adapter. Instruction, memory,
SPI, MMIO, timeout, invalid-memory, and SPI-write events are recorded in one
JSONL trace. Unknown platform addresses remain hard stops.

For the preserved image, the strict attempt now reaches a stronger boundary:

- SHA-256: `080638a445737941336a79db056e64c0090241f3ac52c460fb5e3c0b20a20e2f`;
- format: Intel ME 11-style descriptor/FPT/FTPR/CPD;
- module ISA: x86-32, little-endian;
- CPD entries: 47;
- reset vector: supplied by the absent ME ROM, not present in the SPI dump;
- entry metadata: `rbe` process entry `0x4020a`, code base `0x40000`, offset
  `0x20a`, from the bounded CSE process-attributes extension;
- Huffman: `rbe` stored `0x2610` bytes decoded to `0x4000` bytes; decoded SHA-256
  `0f14830bfd22237b8e7ae06857f19d74eea8aabccd24bb0ffc3d2d6c34ed0668`;
- valid code extent: `0x29c6` bytes; the remaining `0xd3a` bytes are retained
  as module data capacity, not executable code;
- instructions executed: `0`;
- MMIO accesses: `0`.

The exact stop was:

```text
STOP before instruction fetch: the image supplies a bounded module entry
(rbe at 0x4020a), but authentication has not been cryptographically accepted.
Decompression succeeded; no security check was bypassed.
```

With the explicit emulator-only gate option, the same real image now reaches
40 instructions / 106 instruction bytes. The evidence-derived global BSS
window `0x06040000-0x06047004` is writable because the real code initializes
it, stores the pointer `0x06041288`, and embeds the metadata-sized end address
`0x06047004`. The next stop is an external fetch at `0x103d`, reached by the
real call at `0x419bd`; that address is outside the decoded module and is
treated as a missing ME ROM/library dependency. This is real-byte execution,
not a synthetic boot and not a claim that Intel authentication was bypassed on
hardware.

## Fault backward slice

The final instruction is:

```text
0x4001d: 89 48 fc    mov dword ptr [eax-4], ecx
```

The access is a 4-byte write to `0x06040000` with value `0x06041288`.
Immediately before the write, the same real bytes execute:

```text
0x40001: b8 00 00 04 06    mov eax, 0x06040000
0x40008: ba 00 30 04 00    mov edx, 0x00043000
0x40017: 83 c0 04          add eax, 4
0x4001a: 8b 4a fc          mov ecx, dword ptr [edx-4]
```

Register state captured at the stop:

| Register | Value |
| --- | --- |
| `EAX` | `0x06040004` |
| `EBX` | `0x00000000` |
| `ECX` | `0x06041288` |
| `EDX` | `0x00043004` |
| `ESI` | `0x00000000` |
| `EDI` | `0x00000000` |
| `EBP` | `0x00045fe8` |
| `ESP` | `0x00045fe8` |
| `EIP` | `0x0004001d` |
| `EFLAGS` | `0x00000002` |

Thus the source read is from `0x43000`, which is inside the decoded module
capacity (`0x40000 + 0x4000`) but outside its executable extent
(`0x40000 + 0x29c6`). The target is supported as a bounded global/BSS window
for this emulation attempt, not as ordinary RAM or MMIO: the image contains
the base, the pointer inside the window, and the BSS-sized end address. Every
other unmapped address remains a hard stop.

The runtime now derives the evidence-backed layout as follows:

| Range | Source | Runtime treatment |
| --- | --- | --- |
| `0x40000-0x429c6` | process code size | executable code |
| `0x429c6-0x44000` | decoded module capacity minus code size | readable module data |
| `0x45000-0x46000` | thread extension stack size `0x1000` | writable stack |
| `0x46000-0x47000` | default heap size `0x1000` | writable heap |
| `0x47000-0x4e004` | meloader-derived process layout | writable loader-layout BSS |
| `0x06040000-0x06047004` | real rbe literals plus metadata BSS size | evidence-derived writable global/BSS window |

The next blocker is the external call target `0x103d`. The preserved SPI image
contains no verified reset ROM/library bytes for that address, so mapping or
stubbing it would fabricate execution rather than advance the real firmware
trace.

This follows the public loader's text/rodata/guard/stack/heap/BSS ordering and
its requirement for a ROM/library environment, while preserving the target
image's own bounds. See the [public meloader loader map](https://github.com/peterbjornx/meloader/blob/master/user/loader/map.c)
and [ME11 configuration](https://github.com/peterbjornx/meloader/blob/master/cfg/csme.cfg).
