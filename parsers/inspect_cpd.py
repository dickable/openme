"""Read-only Code Partition Directory (CPD) metadata inspector.

This tool inventories the CPD directory at the beginning of an FTPR ME
partition. It reports names, packed relative offsets, sizes, flags, and
hashes of the described ranges. It never writes, extracts, executes, or
modifies firmware content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import string
import sys
from pathlib import Path

try:
    from .inspect_me import inspect_me
except ImportError:  # pragma: no cover - supports direct script execution
    from inspect_me import inspect_me

CPD_SIGNATURE = b"$CPD/"
CPD_FIRST_ENTRY_OFFSET = 0x0C
CPD_MANIFEST_NAME_SIZE = 12
CPD_ENTRY_NAME_SIZE = 12
CPD_FIELDS_SIZE = 12
CPD_MANIFEST_TRAILING_SIZE = 4
MAX_CPD_ENTRIES = 512


def _decode_name(raw: bytes) -> str | None:
    """Decode a fixed-size CPD name only when it is safely printable."""

    text = raw.split(b"\0", 1)[0]
    if not text or any(byte not in string.printable.encode("ascii") for byte in text):
        return None
    try:
        return text.decode("ascii")
    except UnicodeDecodeError:
        return None


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def parse_cpd_directory(data: bytes) -> dict:
    """Parse CPD directory metadata from the start of an FTPR partition."""

    result = {
        "signature": None,
        "signature_offset": None,
        "entries": [],
        "directory_end": None,
        "warnings": [],
        "interpretation": (
            "CPD directory metadata only; packed offsets, sizes, and flags "
            "are reported without assigning undocumented semantic meaning."
        ),
    }
    signature_offset = data.find(CPD_SIGNATURE, 0, min(len(data), 0x1000))
    if signature_offset < 0:
        result["warnings"].append("$CPD/ signature not found in the first 4 KiB")
        return result

    result["signature"] = CPD_SIGNATURE.decode("ascii")
    result["signature_offset"] = signature_offset
    position = signature_offset + CPD_FIRST_ENTRY_OFFSET

    # The first CPD record is 28 bytes: a 12-byte name, three 32-bit fields,
    # and a four-byte trailing area. Subsequent records are 24 bytes. This
    # layout is observed directly in the supplied image.
    for index in range(MAX_CPD_ENTRIES):
        name_size = CPD_MANIFEST_NAME_SIZE if index == 0 else CPD_ENTRY_NAME_SIZE
        record_size = name_size + CPD_FIELDS_SIZE
        if index == 0:
            record_size += CPD_MANIFEST_TRAILING_SIZE
        if position + record_size > len(data):
            result["warnings"].append("CPD directory entry is truncated")
            break

        name_field = data[position:position + name_size]
        name = _decode_name(name_field)
        if name is None:
            result["directory_end"] = position
            break

        packed_offset = _u32(data, position + name_size)
        size = _u32(data, position + name_size + 4)
        trailing_word = _u32(data, position + name_size + 8)
        relative_offset = packed_offset & 0x00FFFFFF
        flags = packed_offset >> 24
        item = {
            "index": index,
            "name": name,
            "name_field_size": name_size,
            "entry_offset": position,
            "packed_offset": packed_offset,
            "offset_in_partition": relative_offset,
            "size": size,
            "flags": flags,
            "trailing_word": trailing_word,
        }
        if relative_offset + size > len(data):
            item["sha256"] = None
            result["warnings"].append(
                f"CPD entry {name} extends beyond the FTPR partition"
            )
        else:
            item["sha256"] = hashlib.sha256(
                data[relative_offset:relative_offset + size]
            ).hexdigest()
        result["entries"].append(item)
        position += record_size
    else:
        result["warnings"].append(f"CPD entry count reached safety limit {MAX_CPD_ENTRIES}")

    if result["directory_end"] is None:
        result["directory_end"] = position
    result["entry_count"] = len(result["entries"])
    return result


def inspect_cpd(path: Path) -> dict:
    """Inspect the FTPR CPD directory in a descriptor-based SPI image."""

    try:
        image = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read image: {exc}") from exc

    me = inspect_me(path)
    ftpr = next(
        (item for item in (me.get("fpt") or {}).get("partitions", [])
         if item["name"] == "FTPR" and item["size"]),
        None,
    )
    result = {
        "path": str(path),
        "image_size": len(image),
        "sha256": hashlib.sha256(image).hexdigest(),
        "ftpr_partition": ftpr,
        "cpd": None,
        "warnings": list(me.get("warnings", [])),
    }
    if ftpr is None or ftpr["absolute_offset"] is None:
        result["warnings"].append("FTPR partition was not identified")
        return result

    start = ftpr["absolute_offset"]
    end = start + ftpr["size"]
    if end > len(image):
        result["warnings"].append("FTPR partition extends beyond the image")
        return result
    result["cpd"] = parse_cpd_directory(image[start:end])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_cpd(args.image)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
