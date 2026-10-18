"""Bounded peripheral adapter for the real-byte Unicorn attempt.

The firmware bytes remain the only executable source.  This adapter mirrors
the address ranges and register semantics of ``openme_me_platform.c`` so
defined SPI/PCH/MEI accesses are observable instead of being zero-filled.
Unknown addresses are intentionally left to Unicorn's invalid-memory stop.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


SPI_BASE = 0x10000000
PCH_BASE = 0x20000000
PCH_SIZE = 0x10000
MEI_BASE = 0x20010000
MEI_SIZE = 0x1000

PCH_CLOCK_CONTROL = 0x00
PCH_POWER_CONTROL = 0x04
PCH_RESET_CONTROL = 0x08
PCH_STATUS = 0x0C
PCH_SPI_COMMAND = 0x100
PCH_SPI_ADDRESS = 0x104
PCH_SPI_STATUS = 0x10C


@dataclass
class RealImageHostPlatform:
    """Stateful, read-only-image peripheral model used by real execution."""

    spi_image: bytes
    clock_control: int = 0
    power_control: int = 0
    reset_control: int = 1
    spi_command: int = 0
    spi_address: int = 0
    mei_ready: bool = False
    spi_reads: int = 0

    def step_to_mei_ready(self) -> None:
        """Perform only the platform phases represented by the QEMU model."""

        self.clock_control = 1
        self.power_control = 1
        self.reset_control = 0
        self.mei_ready = True

    @staticmethod
    def _scalar(data: bytes) -> int:
        if len(data) not in (1, 2, 4):
            raise ValueError("peripheral scalar must be 1, 2, or 4 bytes")
        return int.from_bytes(data, "little")

    def read(self, address: int, size: int) -> int | None:
        if address >= SPI_BASE and address + size <= SPI_BASE + len(self.spi_image):
            self.spi_reads += 1
            return self._scalar(self.spi_image[address - SPI_BASE : address - SPI_BASE + size])
        if PCH_BASE <= address and address + size <= PCH_BASE + PCH_SIZE:
            if size != 4 or address & 3:
                return None
            offset = address - PCH_BASE
            status = (
                (1 if self.clock_control else 0)
                | (2 if self.power_control else 0)
                | (4 if not self.reset_control else 0)
                | 8
                | (16 if self.mei_ready else 0)
            )
            values = {
                PCH_CLOCK_CONTROL: self.clock_control,
                PCH_POWER_CONTROL: self.power_control,
                PCH_RESET_CONTROL: self.reset_control,
                PCH_STATUS: status,
                PCH_SPI_COMMAND: self.spi_command,
                PCH_SPI_ADDRESS: self.spi_address,
                PCH_SPI_STATUS: 1,
            }
            return values.get(offset)
        if MEI_BASE <= address and address + size <= MEI_BASE + MEI_SIZE:
            return 1 if self.mei_ready else 0
        return None

    def write(self, address: int, size: int, value: int) -> bool:
        if PCH_BASE <= address and address + size <= PCH_BASE + PCH_SIZE:
            if size != 4 or address & 3:
                return False
            offset = address - PCH_BASE
            if offset == PCH_CLOCK_CONTROL:
                self.clock_control = value & 1
            elif offset == PCH_POWER_CONTROL:
                self.power_control = value & 2
            elif offset == PCH_RESET_CONTROL:
                self.reset_control = value & 1
            elif offset == PCH_SPI_COMMAND:
                self.spi_command = value & 0xFF
            elif offset == PCH_SPI_ADDRESS:
                self.spi_address = value
            else:
                return False
            return True
        return MEI_BASE <= address and address + size <= MEI_BASE + MEI_SIZE

    def pch_snapshot(self) -> bytes:
        data = bytearray(PCH_SIZE)
        values = {
            PCH_CLOCK_CONTROL: self.clock_control,
            PCH_POWER_CONTROL: self.power_control,
            PCH_RESET_CONTROL: self.reset_control,
            PCH_STATUS: self.read(PCH_BASE + PCH_STATUS, 4) or 0,
            PCH_SPI_COMMAND: self.spi_command,
            PCH_SPI_ADDRESS: self.spi_address,
            PCH_SPI_STATUS: 1,
        }
        for offset, value in values.items():
            struct.pack_into("<I", data, offset, value)
        return bytes(data)


__all__ = ["MEI_BASE", "PCH_BASE", "PCH_SIZE", "RealImageHostPlatform", "SPI_BASE"]
