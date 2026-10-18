# Safety and recovery

- Work only with legally obtained firmware and hardware.
- Before any modification, make at least two independent full SPI dumps and verify that they match where expected.
- Hash and preserve original dumps as immutable reference material; never overwrite the originals.
- Use a sacrificial test machine, not a daily-use laptop.
- Obtain and validate an external SPI programmer and recovery points before any modification is considered.
- Never test an unknown image on a daily-use laptop.
- Never flash experimental firmware during the initial phase.
- Do not attempt to bypass signature verification, platform authentication, Boot Guard, or other security protections.
- Keep experiments reversible, documented, and reproducible.

The initial phase is limited to documentation, parsing, emulation, protocol observation, and read-only analysis.

