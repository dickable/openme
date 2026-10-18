# ME platform scaffold

OpenME now has a small C reference scaffold in
`csme/bootloader/openme_me_platform.c`. It is intentionally deterministic and
read-only with respect to the supplied SPI image.

The current map is:

| Range | Purpose |
| --- | --- |
| `0x00000000-0x0000ffff` | fake boot ROM |
| `0x00100000-0x0017ffff` | SRAM |
| `0x00200000-0x003fffff` | DRAM |
| `0x10000000+` | read-only SPI image window |
| `0x20000000-0x2000ffff` | fake PCH and SPI-controller registers |
| `0x20010000-0x20010fff` | fake MEI/HECI status window |

The model supplies clock, power, reset, PCH status, SPI command/address/data
state, and MEI readiness. Its startup sequence is:

```text
reset -> rom -> platform-init -> spi-ready -> mei-ready -> auth-pending
```

It then stops at `rejected` because OpenME does not implement or bypass Intel
firmware authentication and does not claim to know how the real ME ROM loads
the signed runtime modules. Reaching this state is a useful harness result,
not evidence of a faithful CSME boot.

Build the standalone probe with MSYS2 UCRT64:

```bash
gcc -std=c11 -Wall -Wextra -Werror \
  csme/bootloader/openme_me_platform.c \
  csme/bootloader/openme_me_platform_demo.c \
  -o qemu-work/openme-me-platform-demo.exe
```

Run it against the exact read-only ME-region copy:

```bash
qemu-work/openme-me-platform-demo.exe \
  qemu-work/t460-me-region-original.bin
```

Build and run the regression test:

```bash
gcc -std=c11 -Wall -Wextra -Werror \
  csme/bootloader/openme_me_platform.c \
  csme/tests/test_openme_me_platform.c \
  -Icsme/bootloader \
  -o qemu-work/test-openme-me-platform.exe
qemu-work/test-openme-me-platform.exe
```

This is the first C implementation layer. The next layer is wiring the same
map into the native QEMU device and replacing guessed register behavior with
documented or experimentally observed contracts. The native QEMU adapter now
exposes the platform state window at BAR0 `0x300-0x318` and accepts a
read-only `spi-image` property; its state transitions are covered by the
tracked QEMU patch.
