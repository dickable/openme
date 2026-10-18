"""Read-only Intel ME/CSME partition-table inspector.

This tool reports the ME region's Firmware Partition Table (FPT) and
partition boundaries. It does not execute modules, extract firmware, modify
images, infer a version from undocumented fields, or flash hardware.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

try:
    from .inspect_ifd import inspect_ifd
except ImportError:  # pragma: no cover - supports direct script execution
    from inspect_ifd import inspect_ifd

FPT_SIGNATURE = b"$FPT"
FPT_ENTRY_SIZE = 0x20
MAX_PARTITIONS = 64


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _find_fpt(data: bytes) -> int | None:
    offset = data.find(FPT_SIGNATURE, 0, min(len(data), 0x1000))
    return offset if offset >= 0 else None


def _inspect_mn2_headers(data: bytes) -> list[dict]:
    """Record repeated MN2 header candidates without assigning semantics."""

    headers = []
    search_from = 0
    while len(headers) < 32:
        offset = data.find(b"$MN2", search_from)
        if offset < 0 or offset + 16 > len(data):
            break
        words = [u16(data, offset + 8 + index * 2) for index in range(4)]
        headers.append({
            "offset_in_me_region": offset,
            "candidate_16bit_tuple": words,
            "interpretation": "undocumented candidate fields; not asserted as the CSME marketing version",
        })
        search_from = offset + 4
    return headers


def inspect_me(path: Path) -> dict:
    try:
        image = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read image: {exc}") from exc

    ifd = inspect_ifd(path)
    me_region = next((region for region in ifd.get("regions", [])
                      if region["name"] == "Intel ME" and region["size"]), None)
    result = {
        "path": str(path),
        "image_size": len(image),
        "sha256": hashlib.sha256(image).hexdigest(),
        "me_region": me_region,
        "fpt": None,
        "warnings": list(ifd.get("warnings", [])),
    }
    if me_region is None or me_region["offset"] is None:
        result["warnings"].append("Intel ME region was not identified by the descriptor")
        return result

    start = me_region["offset"]
    end = start + me_region["size"]
    region = image[start:end]
    fpt_offset = _find_fpt(region)
    if fpt_offset is None:
        result["warnings"].append("$FPT signature not found in the first 4 KiB of the ME region")
        return result
    if fpt_offset + 0x20 > len(region):
        result["warnings"].append("FPT header is truncated")
        return result

    partition_count = u32(region, fpt_offset + 4)
    header_version = region[fpt_offset + 8]
    entry_version = region[fpt_offset + 9]
    header_length = region[fpt_offset + 10]
    entry_table = fpt_offset + header_length
    fpt = {
        "offset_in_me_region": fpt_offset,
        "absolute_offset": start + fpt_offset,
        "partition_count": partition_count,
        "header_version": header_version,
        "entry_version": entry_version,
        "header_length": header_length,
        "partitions": [],
    }
    if not 0x20 <= header_length <= 0x100 or entry_table > len(region):
        result["warnings"].append("FPT header length is outside the safe inspection range")
        result["fpt"] = fpt
        return result
    if partition_count > MAX_PARTITIONS:
        result["warnings"].append(f"FPT partition count exceeds {MAX_PARTITIONS}")
        partition_count = MAX_PARTITIONS

    for index in range(partition_count):
        offset = entry_table + index * FPT_ENTRY_SIZE
        if offset + FPT_ENTRY_SIZE > len(region):
            result["warnings"].append("FPT partition table is truncated")
            break
        name = region[offset:offset + 4].rstrip(b"\0").decode("ascii", "replace")
        partition_offset = u32(region, offset + 8)
        partition_size = u32(region, offset + 12)
        item = {
            "index": index,
            "name": name,
            "offset_in_me_region": partition_offset,
            "absolute_offset": start + partition_offset,
            "size": partition_size,
            "end_in_me_region": partition_offset + partition_size,
        }
        if partition_offset + partition_size > len(region):
            item["sha256"] = None
            result["warnings"].append(f"FPT partition {name or index} extends beyond the ME region")
        else:
            item["sha256"] = hashlib.sha256(
                region[partition_offset:partition_offset + partition_size]
            ).hexdigest()
        fpt["partitions"].append(item)

    result["fpt"] = fpt
    result["mn2_headers"] = _inspect_mn2_headers(region)
    result["version_status"] = (
        "not asserted: FPT and MN2 candidate fields identify structure, not a "
        "reliable CSME marketing version"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_me(args.image)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
