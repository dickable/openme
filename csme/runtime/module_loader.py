"""Bounded CPD module loading for the real-image execution attempt.

The loader never rewrites the SPI dump. It only creates an in-memory view of
an image range after checking CPD and module-metadata bounds. For ME11, the
CPD offset attribute's bit 25 identifies Huffman storage; metadata supplies
the bounded stored length when CPD's nominal length is an uncompressed size.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

CPD_FLAG_UNCOMPRESSED = 0
CPD_FLAG_HUFFMAN = 2


def compression_name(flags: int) -> str:
    if flags == CPD_FLAG_UNCOMPRESSED:
        return "uncompressed"
    if flags == CPD_FLAG_HUFFMAN:
        return "huffman"
    return f"unknown-flag-0x{flags:x}"


@dataclass(frozen=True)
class ModuleCandidate:
    name: str
    image_offset: int
    size: int
    guest_base: int
    flags: int
    bounds_valid: bool
    load_status: str
    compression: str = "unknown"
    executable_candidate: bool = False
    declared_size: int = 0
    uncompressed_size: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "image_offset": f"0x{self.image_offset:x}",
            "size": f"0x{self.size:x}",
            "declared_size": f"0x{self.declared_size:x}",
            "uncompressed_size": f"0x{self.uncompressed_size:x}",
            "guest_base": f"0x{self.guest_base:x}",
            "flags": f"0x{self.flags:x}",
            "bounds_valid": self.bounds_valid,
            "load_status": self.load_status,
            "compression": self.compression,
            "executable_candidate": self.executable_candidate,
        }


@dataclass(frozen=True)
class ModuleLoaderPlan:
    profile: str
    modules: tuple[ModuleCandidate, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    execution_ready: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "modules": [module.as_dict() for module in self.modules],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "execution_ready": self.execution_ready,
        }


@dataclass(frozen=True)
class LoadedModule:
    """An immutable, bounded view of bytes from the preserved image."""

    candidate: ModuleCandidate
    data: bytes
    sha256: str
    valid_extent: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.candidate.name,
            "image_offset": f"0x{self.candidate.image_offset:x}",
            "size": len(self.data),
            "capacity": len(self.data),
            "valid_extent": len(self.data) if self.valid_extent is None else self.valid_extent,
            "sha256": self.sha256,
            "compression": self.candidate.compression,
            "verified_bounded": True,
        }


def build_module_plan(
    *,
    cpd_entries: Iterable[dict[str, Any]],
    ftpr_absolute_offset: int,
    ftpr_size: int,
    me_absolute_offset: int,
    profile: str,
    image_size: int | None = None,
    module_sizes: dict[str, dict[str, int]] | None = None,
) -> ModuleLoaderPlan:
    """Validate CPD ranges and classify their stored representation."""

    modules: list[ModuleCandidate] = []
    errors: list[str] = []
    warnings: list[str] = []
    spans: list[tuple[int, int, str]] = []

    for index, entry in enumerate(cpd_entries):
        name = str(entry.get("name") or f"entry-{index}")
        relative_offset = int(entry.get("offset_in_partition", -1))
        size = int(entry.get("size", -1))
        flags = int(entry.get("flags", 0))
        raw_offset = int(entry.get("packed_offset", -1))
        metadata_sizes = (module_sizes or {}).get(name, {})
        stored_size = int(metadata_sizes.get("stored_size", size))
        uncompressed_size = int(metadata_sizes.get("uncompressed_size", size))
        if raw_offset >= 0:
            compression = "huffman" if raw_offset & 0x02000000 else "uncompressed"
        else:
            compression = compression_name(flags)
        valid = (
            0 <= relative_offset <= ftpr_size
            and 0 <= stored_size <= ftpr_size
            and relative_offset + stored_size <= ftpr_size
        )
        image_offset = ftpr_absolute_offset + max(relative_offset, 0)
        if image_size is not None and image_offset + max(stored_size, 0) > image_size:
            valid = False
            errors.append(f"{name}: range exceeds preserved image size")

        executable_candidate = (
            valid
            and compression == "uncompressed"
            and stored_size > 0
            and not name.endswith((".met", ".man"))
        )
        if not valid:
            status = "rejected-out-of-bounds"
        elif compression == "huffman":
            status = "bounded-compressed-not-executable"
        elif compression == "uncompressed" and not executable_candidate:
            status = "bounded-metadata-not-executable"
        elif compression == "uncompressed":
            status = "bounded-uncompressed-candidate"
        else:
            status = "rejected-unknown-compression"
            errors.append(f"{name}: unsupported CPD compression flag 0x{flags:x}")

        modules.append(
            ModuleCandidate(
                name=name,
                image_offset=image_offset,
                size=max(stored_size, 0),
                guest_base=0x10000000 + max(image_offset - me_absolute_offset, 0),
                flags=flags,
                bounds_valid=valid,
                load_status=status,
                compression=compression,
                executable_candidate=executable_candidate,
                declared_size=max(size, 0),
                uncompressed_size=max(uncompressed_size, 0),
            )
        )
        if not valid:
            errors.append(
                f"{name}: range offset=0x{relative_offset:x}, stored_size=0x{stored_size:x} "
                f"exceeds FTPR size 0x{ftpr_size:x}"
            )
            continue
        if stored_size:
            span = (relative_offset, relative_offset + stored_size, name)
            for left, right, other in spans:
                if relative_offset < right and left < relative_offset + stored_size:
                    warnings.append(
                        f"{name}: overlaps stored CPD range {other}; metadata length applied"
                    )
            spans.append(span)

    return ModuleLoaderPlan(
        profile=profile,
        modules=tuple(modules),
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(warnings),
        execution_ready=any(module.executable_candidate for module in modules),
    )


def load_bounded_module(
    image: bytes, candidate: ModuleCandidate, *, image_sha256: str | None = None
) -> LoadedModule:
    """Copy one verified, bounded uncompressed range into emulator memory."""

    if image_sha256 is not None and len(image_sha256) != 64:
        raise ValueError("image_sha256 must be a lowercase or uppercase SHA-256")
    start = candidate.image_offset
    end = start + candidate.size
    if not candidate.bounds_valid or start < 0 or end > len(image):
        raise ValueError(f"{candidate.name}: image range is not bounded")
    if not candidate.executable_candidate:
        raise ValueError(
            f"{candidate.name}: {candidate.load_status}; stored bytes are not executable"
        )
    data = bytes(image[start:end])
    return LoadedModule(candidate=candidate, data=data, sha256=hashlib.sha256(data).hexdigest())


def load_verified_module_bytes(
    candidate: ModuleCandidate,
    data: bytes,
    *,
    expected_size: int | None = None,
    valid_extent: int | None = None,
) -> LoadedModule:
    """Create a loaded view from verified decoder output, never from padding.

    The caller must have obtained ``data`` from the bounded image range and a
    strict format decoder.  This helper deliberately does not accept a size
    mismatch or mark compressed bytes executable.
    """

    if not candidate.bounds_valid:
        raise ValueError(f"{candidate.name}: candidate range is not bounded")
    if expected_size is not None and len(data) != expected_size:
        raise ValueError(
            f"{candidate.name}: decoded size 0x{len(data):x} does not match "
            f"metadata size 0x{expected_size:x}"
        )
    if not data:
        raise ValueError(f"{candidate.name}: decoded module is empty")
    if valid_extent is not None and not 0 < valid_extent <= len(data):
        raise ValueError(
            f"{candidate.name}: valid module extent 0x{valid_extent:x} exceeds decoded capacity "
            f"0x{len(data):x}"
        )
    executable = ModuleCandidate(
        name=candidate.name,
        image_offset=candidate.image_offset,
        size=len(data),
        guest_base=candidate.guest_base,
        flags=candidate.flags,
        bounds_valid=True,
        load_status="bounded-decoded-executable",
        compression=candidate.compression,
        executable_candidate=True,
        declared_size=candidate.declared_size,
        uncompressed_size=len(data),
    )
    return LoadedModule(
        candidate=executable,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        valid_extent=valid_extent,
    )


__all__ = [
    "CPD_FLAG_HUFFMAN",
    "CPD_FLAG_UNCOMPRESSED",
    "LoadedModule",
    "ModuleCandidate",
    "ModuleLoaderPlan",
    "build_module_plan",
    "compression_name",
    "load_bounded_module",
    "load_verified_module_bytes",
]
