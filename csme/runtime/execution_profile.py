"""Versioned execution profile for the isolated T460 real-image attempt."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRegion:
    name: str
    base: int
    size: int
    permissions: str
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "base": f"0x{self.base:x}",
            "size": f"0x{self.size:x}",
            "permissions": self.permissions,
            "source": self.source,
        }


@dataclass(frozen=True)
class ExecutionProfile:
    name: str
    platform: str
    cpu_status: str
    isa: str
    word_size_bits: int
    endianness: str
    instruction_execution_enabled: bool
    memory_regions: tuple[MemoryRegion, ...]
    unsupported_requirements: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "platform": self.platform,
            "cpu_status": self.cpu_status,
            "isa": self.isa,
            "word_size_bits": self.word_size_bits,
            "endianness": self.endianness,
            "instruction_execution_enabled": self.instruction_execution_enabled,
            "memory_regions": [region.as_dict() for region in self.memory_regions],
            "unsupported_requirements": list(self.unsupported_requirements),
        }


SKYLAKE_T460_PROFILE = ExecutionProfile(
    name="skylake-t460-real-image-v1",
    platform="Skylake / Sunrise Point-LP / ThinkPad T460-class target",
    cpu_status="32-bit x86 module ISA identified; reset ROM and entry state remain image-external",
    isa="x86-32",
    word_size_bits=32,
    endianness="little",
    instruction_execution_enabled=True,
    memory_regions=(
        MemoryRegion("rom", 0x00000000, 0x00010000, "r-x", "required external ME ROM; unavailable"),
        MemoryRegion("sram", 0x00100000, 0x00080000, "rw-", "isolated runtime"),
        MemoryRegion("dram", 0x00200000, 0x00200000, "rw-", "bounded host grant"),
        MemoryRegion("spi-window", 0x10000000, 0, "r-x", "preserved image bounds only"),
        MemoryRegion("pch-mmio", 0x20000000, 0x00010000, "rw-", "isolated QEMU model"),
        MemoryRegion("mei-mmio", 0x20010000, 0x00001000, "rw-", "isolated MEI model"),
    ),
    unsupported_requirements=(
        "Intel ME reset ROM/library image",
        "decoded executable entry metadata for a selected module",
        "verified module decompression for Huffman candidates",
        "cryptographically accepted image authentication state",
        "interrupt/trap vectors and segment state from the target runtime",
        "complete PCH, DMA, power-management, and host-memory behavior",
    ),
)


def profile_for_target(name: str = SKYLAKE_T460_PROFILE.name) -> ExecutionProfile:
    if name not in {SKYLAKE_T460_PROFILE.name, "skylake-t460-research-v0"}:
        raise ValueError(f"unknown execution profile: {name}")
    return SKYLAKE_T460_PROFILE


__all__ = ["ExecutionProfile", "MemoryRegion", "SKYLAKE_T460_PROFILE", "profile_for_target"]
