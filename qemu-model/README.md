# QEMU model

The CSME-specific platform and runtime work now lives under [`csme/`](../csme/):

- [`csme/bootloader/`](../csme/bootloader/) — native C platform and startup scaffold
- [`csme/fake_devices/`](../csme/fake_devices/) — deterministic host-facing devices
- [`csme/qemu/`](../csme/qemu/) — tracked native QEMU patch and build instructions
- [`csme/runtime/`](../csme/runtime/) — synthetic boot/runtime model
- [`csme/mei/`](../csme/mei/) — MEI/HBM transport models
- [`csme/cpu/`](../csme/cpu/) — optional Unicorn CPU sandbox
- [`csme/tests/`](../csme/tests/) — CSME component tests

This directory remains as a compatibility pointer for the old project layout.
The local QEMU checkout under `qemu-work/` is ignored and is not part of the
source of record.
