# CSME boot research

This directory contains everything related to modeling and eventually
reproducing the boot/runtime environment around Intel CSME on the selected
Skylake platform.

The current work is an isolated research scaffold with a real-byte execution
attempt. It inspects a preserved ME-region copy read-only, builds bounded
memory mappings, models platform state and host-facing peripherals, and uses a
strict x86-32 Unicorn backend when the image supplies verified entry/runtime
metadata. It never bypasses signing or platform security, and it reports a
controlled pre-fetch stop when the image cannot legally and technically be
started.

## Layout

- `bootloader/` — native C startup, memory-map, clock/reset, and SPI scaffold
- `platform/` — future PCH, power-management, DMA, and sideband models
- `fake_devices/` — deterministic host-facing and fake-device contracts
- `spi/` — SPI-region access and flash-layout experiments
- `qemu/` — native QEMU patch and application instructions
- `runtime/` — synthetic boot/runtime and filesystem model
- `mei/` — MEI/HBM transport and mailbox bridge models
- `cpu/` — synthetic Unicorn tests and CPU integration notes
- `runtime/real_firmware_runtime.py` — bounded real-byte Unicorn backend
- `tests/` — C and Python regression tests
- `docs/` — CSME-specific design notes

The real-image preflight procedure and current result are documented in
[`docs/real-image-attempt.md`](docs/real-image-attempt.md).

Original firmware remains under `downloaded-firmware/` and is not moved or
modified by this organization change.
