# Skylake platform notes

- Skylake uses platform-specific PCH and firmware configuration. Board design, chipset variant, flash layout, straps, and firmware policy all matter.
- Skylake/Kaby Lake platforms require Intel FSP for host initialization; the exact FSP generation and integration are platform-dependent.
- ME firmware is not interchangeable across arbitrary boards. Compatibility must be demonstrated for one specific platform, not inferred from CPU family names alone.
- ThinkPad models may include platform security features such as Boot Guard. These protections and their configuration must be documented, not bypassed.

These notes are hypotheses and research boundaries until confirmed against lawful, preserved firmware samples and public technical documentation.

