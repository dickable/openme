# Project scope

OpenME starts with one specific Skylake platform rather than attempting to cover every CPU, PCH, or laptop at once. The eventual reference target is a legally obtained Lenovo ThinkPad T460-class machine, but the initial work is software-only.

The research will focus on:

- SPI flash regions and their layout.
- ME metadata and firmware-image structure.
- Host-to-ME interfaces and observable message behavior.
- Boot dependencies, power-management interactions, and platform initialization.
- Reproducible parsers, fixtures, tests, and software models.

Software models come before hardware experiments. The project does not bypass signature verification, platform authentication, or other security protections, and it does not make claims that an open-source replacement is currently possible.

