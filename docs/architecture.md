# Architecture

The working platform model includes these components:

- **CPU/PCH:** the processor and platform controller hub that provide the host, chipset, buses, reset, and power-management behavior.
- **Host firmware/BIOS:** firmware that initializes the host and coordinates platform boot.
- **Intel ME/CSME:** a separate platform-management subsystem whose firmware and configuration are coupled to the platform.
- **SPI flash descriptor:** the flash layout and access-control metadata.
- **BIOS, ME, and GbE regions:** common regions in a platform SPI image; exact layouts and contents must be verified per image.
- **Host-to-ME communication:** interfaces and messages exchanged during initialization and runtime, to be studied through documentation, parsing, emulation, and controlled observation.
- **Power-management and boot interactions:** dependencies between reset, sleep states, power sequencing, host initialization, and ME availability.

The architecture notes are intentionally descriptive. They are not instructions for bypassing authentication or modifying a live platform.

