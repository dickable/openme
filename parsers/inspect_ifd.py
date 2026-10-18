"""Read-only Intel Flash Descriptor region inspector for raw SPI images.

This tool only reads an image. It does not extract, rewrite, or flash regions.
It supports the descriptor fields needed to identify the common Skylake-era
descriptor and flash-region boundaries; it is not a replacement for ifdtool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

FD_SIGNATURE = 0x0FF0A55A
FD_SIGNATURE_OFFSET = 0x10
DESCRIPTOR_SIZE = 0x1000
REGION_NAMES = [
    "Flash Descriptor", "BIOS", "Intel ME", "GbE", "Platform Data",
    "Device Exp1", "Secondary BIOS", "Reserved", "EC", "Device Exp2",
    "IE", "10GbE_0", "10GbE_1", "Reserved", "Reserved", "PTT",
]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def inspect_ifd(path: Path) -> dict:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read image: {exc}") from exc
    result = {"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    descriptor_offset = None
    for offset in range(0, max(0, len(data) - 3), 4):
        if u32(data, offset) == FD_SIGNATURE:
            descriptor_offset = offset
            break
    if descriptor_offset is None:
        result["descriptor"] = None
        result["warnings"] = ["Intel Flash Descriptor signature not found"]
        return result
    if descriptor_offset + DESCRIPTOR_SIZE > len(data):
        result["descriptor"] = None
        result["warnings"] = ["descriptor begins but the 4 KiB descriptor is truncated"]
        return result

    # The signature is at offset 0x10 within the descriptor.  The FLMAP
    # pointers and region offsets are relative to the descriptor base, not to
    # the signature word itself.
    descriptor_base = (
        descriptor_offset - FD_SIGNATURE_OFFSET
        if descriptor_offset >= FD_SIGNATURE_OFFSET else 0
    )
    flmap0 = u32(data, descriptor_offset + 4)
    flmap1 = u32(data, descriptor_offset + 8)
    flmap2 = u32(data, descriptor_offset + 12)
    frba = descriptor_base + (((flmap0 >> 16) & 0xFF) << 4)
    # Skylake-era IFDv2 uses 15-bit region base/limit fields and up to 16 entries.
    result["descriptor"] = {
        "base": descriptor_base,
        "offset": descriptor_offset,
        "signature": f"0x{FD_SIGNATURE:08x}",
        "flmap0": f"0x{flmap0:08x}",
        "flmap1": f"0x{flmap1:08x}",
        "flmap2": f"0x{flmap2:08x}",
        "region_table_offset": frba,
    }
    warnings = []
    if frba < descriptor_offset or frba + len(REGION_NAMES) * 4 > descriptor_offset + DESCRIPTOR_SIZE:
        warnings.append("region table offset is outside the 4 KiB descriptor")
        result["regions"] = []
        result["warnings"] = warnings
        return result

    regions = []
    valid_ranges = []
    for index, name in enumerate(REGION_NAMES):
        entry_offset = frba + index * 4
        flreg = u32(data, entry_offset)
        base = (flreg & 0x7FFF) << 12
        limit = (((flreg >> 16) & 0x7FFF) << 12) | 0xFFF
        unused = flreg in (0x00007FFF, 0xFFFFFFFF) or (
            base == 0 and limit == 0xFFF and index != 0
        )
        item = {"index": index, "name": name, "flreg": f"0x{flreg:08x}"}
        if unused:
            item.update({"offset": None, "size": 0, "end": None, "sha256": None})
        elif limit < base:
            warnings.append(f"{name} region has a limit below its base")
            item.update({"offset": base, "size": 0, "end": limit, "sha256": None})
        else:
            end = limit + 1
            item.update({"offset": base, "size": end - base, "end": limit, "sha256": None})
            if end > len(data):
                warnings.append(f"{name} region extends beyond the image")
            else:
                item["sha256"] = hashlib.sha256(data[base:end]).hexdigest()
                valid_ranges.append((base, end, name))
        regions.append(item)

    for index, (left_base, left_end, left_name) in enumerate(valid_ranges):
        for right_base, right_end, right_name in valid_ranges[index + 1 :]:
            if left_base < right_end and right_base < left_end:
                warnings.append(f"{left_name} and {right_name} regions overlap")

    result["regions"] = regions
    result["warnings"] = warnings
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_ifd(args.image)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, indent=2, sort_keys=True))

