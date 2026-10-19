# Applying the native QEMU prototype

`openme-qemu.patch` is the reproducibility artifact for the native prototype.
It captures the two source files and the two QEMU Meson build-list edits needed
to compile and run the QTest. It does not vendor QEMU or modify this OpenME
repository when applied.

## Requirements

- A clean QEMU source checkout. The artifact was prepared against the local
  QEMU 11.1.50 development checkout used by OpenME.
- A QEMU build configured for `x86_64-softmmu`.
- A normal QEMU build toolchain with GLib, Meson, and Ninja.

## Apply

From the root of the QEMU checkout, run:

```bash
git apply /c/Users/peyton/Documents/openme/csme/qemu/openme-qemu.patch
```

If the checkout is not at the recorded revision, try a three-way application:

```bash
git apply --3way /c/Users/peyton/Documents/openme/csme/qemu/openme-qemu.patch
```

The patch must be applied to QEMU source, not to `openme/`. It adds:

- `hw/misc/openme-pci.c`
- `tests/qtest/openme-pci-test.c`
- one source-list entry in `hw/misc/meson.build`
- one QTest-list entry in `tests/qtest/meson.build`

Reconfigure and build from the QEMU checkout:

```bash
./configure --target-list=x86_64-softmmu --disable-werror \
  --with-pkgversion=openme-local
ninja -C build -j2
```

Run the focused test:

```bash
cd build
export QTEST_QEMU_BINARY=./qemu-system-x86_64.exe
./tests/qtest/openme-pci-test.exe --tap -k
```

The expected test name is `/openme/mmio-contract`. The test checks PCI
enumeration, the version register, reset, `START`, a bounded raw `hello` echo,
one complete v0 framed `DATA` echo, response popping, event counting, suspend,
and interrupt acknowledgement.

The current native register revision is `0x00010001`. TX data is at BAR offset
`0x400` and RX data at `0x600`, each accommodating a complete 272-byte frame.
The older `0x20`/`0x120` layout overlapped by 16 bytes after frame headers were
added. The regression also checks every byte of a maximum-size frame and the
offline peripheral status when platform initialization faults. Update native
clients when moving from revision `0x00010000`; the Python high-level model
does not implement these byte windows.

The MMIO callbacks explicitly support 1-, 2-, and 4-byte accesses, including
unaligned buffer accesses, so QEMU does not widen a final-byte access beyond
the frame boundary.

These are local experimental changes, not an upstream QEMU contribution.

## Limitations

- This is a project-defined fake device, not Intel ME/CSME, HECI, AMT, or a
  replacement for signed firmware.
- The patch contains bounded MMIO payload windows (256-byte payloads and an
  eight-entry response queue), but no DMA path.
- The patch is source-compatible with the recorded QEMU tree, not a promise of
  compatibility with every future QEMU release. If QEMU changes the surrounding
  Meson lists or APIs, application may require a small manual adjustment.
- The artifact has no external dependency on GitHub and does not include a
  QEMU source tree.
