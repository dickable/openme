# QEMU integration

This directory contains the tracked native QEMU patch and instructions for
building the local `openme-me` research device. The device can accept a
read-only SPI-region path and exposes the CSME platform-scaffold state window.

This device model is independent of the source-built firmware under `src/`.
The firmware QEMU test uses a PC CPU and serial port and does not attach
`openme-me`. The local experimental QEMU patch is not intended for upstream
submission; QEMU itself is an [external dependency](https://www.qemu.org/).
