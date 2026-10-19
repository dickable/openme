# Safety and recovery

- Work only with legally obtained firmware and hardware.
- Before a physical flash modification, make at least two independent full SPI
  dumps and verify that they match where expected.
- Hash and preserve original dumps as immutable reference material; never overwrite the originals.
- Use a sacrificial test machine, not a daily-use laptop.
- Establish a board-specific recovery method before a physical write. An external
  programmer is a common recovery path, but its electrical compatibility and
  connection must be checked against the particular board and chip.
- Never test an unknown image on a daily-use laptop.
- Physical flashing is supported by `tools/flash_openme.py`; inspect its offline
  comparison before explicitly authorizing a write. Successful readback proves
  byte programming, not that the board will boot or accept an ME image.
- Keep experiments reversible, documented, and reproducible.

Firmware patches and writable working copies are part of the project. A
software authentication experiment applies only to the environment tested;
record the trace before claiming a check was crossed. The flashing tool does
not suppress flashrom's probe, protection, or verification errors.

