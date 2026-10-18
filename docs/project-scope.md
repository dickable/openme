# Project scope

OpenME starts with one specific Skylake platform rather than attempting to cover every CPU, PCH, or laptop at once. The locked reference target is a legally obtained Lenovo ThinkPad T460 20FM with a non-vPro Intel Core i5-6200U configuration, but the initial work is software-only. See [target-platform.md](target-platform.md) for the boundary conditions.

The research will focus on:

- SPI flash regions and their layout.
- ME metadata and firmware-image structure.
- Host-to-ME interfaces and observable message behavior.
- Boot dependencies, power-management interactions, and platform initialization.
- Reproducible parsers, fixtures, tests, and software models.

Software models come before hardware experiments. The project does not bypass signature verification, platform authentication, or other security protections. An open-source or compatible implementation is a research hypothesis: difficult and unproven for the complete platform, but not assumed impossible.

