# OpenME

OpenME is an open-source research project for studying Intel Management Engine firmware on Skylake platforms through documentation, parsing, emulation, and controlled protocol observation.

## Research goals

- Analyze one legally obtained Skylake platform in depth.
- Understand SPI flash regions, ME metadata, host/ME interfaces, and boot dependencies.
- Build reproducible software models before attempting any hardware work.
- Explore whether a compatible or open-source replacement model is technically feasible, without assuming that it can replace Intel firmware or security functions.

Intel ME/CSME is platform-specific. Firmware, configuration, chipset behavior, security policy, and board integration may differ across CPUs, PCHs, and laptop models; a universal firmware for every Skylake CPU is only a long-term hypothesis.

The initial target is one Skylake ThinkPad platform, eventually a Lenovo ThinkPad T460-class laptop. The first milestone is firmware parsing and a fake/emulated host-facing ME model that responds to controlled test messages.

No hardware flashing happens during the initial phase. Work begins with legally obtained firmware and hardware, and original firmware dumps must always be preserved.

## Roadmap

1. Phase 1: project setup and documentation
2. Phase 2: firmware image parser and metadata inspection
3. Phase 3: QEMU host model and fake ME device
4. Phase 4: protocol and behavior documentation
5. Phase 5: purchase and inspect one T460-class test machine
6. Phase 6: read-only hardware validation
7. Phase 7: carefully controlled experiments with external recovery

See [docs/project-scope.md](docs/project-scope.md), [docs/safety-and-recovery.md](docs/safety-and-recovery.md), and the component-specific notes for the current boundaries.

The CSME boot/platform research tree is organized under [csme/README.md](csme/README.md).

