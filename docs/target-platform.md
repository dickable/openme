# Locked research target

OpenME's first hardware-specific target is one Lenovo ThinkPad T460, machine type **20FM**, with the following reference profile:

- CPU: Intel Core i5-6200U, Skylake-U.
- Graphics: integrated Intel HD Graphics 520; no discrete GPU.
- vPro: non-vPro configuration.
- BIOS reference: Lenovo BIOS 1.45, `R06ET71W`.
- Embedded Controller reference: ECP 1.11, `R06HT31W`.

The CPU and non-vPro choice follow Lenovo's 20FM product specifications. The BIOS and ECP values are a software reference baseline from Lenovo's release history; they are not instructions to flash or proof of the versions installed on a future test machine.

The exact board revision, SPI flash part number, flash size, descriptor permissions, ME version, optional-device configuration, and Boot Guard policy must be discovered from the physical machine. The expected Skylake ThinkPad flash layout is provisional until confirmed by two matching, read-only dumps from that exact board.

This target does not imply that the resulting model will work on other T460 variants, T460s/T460p systems, T470 systems, or arbitrary Skylake platforms.

