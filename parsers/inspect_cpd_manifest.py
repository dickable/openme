"""Read-only inspector for an FTPR CPD manifest/metadata area.

The parser deliberately treats CPD fields as layout data, not as documented
semantics. It validates the fixed-width record layout and bounds before
reporting identifiers, record offsets, raw little-endian words, or a bounded
range candidate derived from the first two words. It never extracts, writes,
executes, or modifies firmware content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from .inspect_me import inspect_me
except ImportError:  # pragma: no cover - supports direct script execution
    from inspect_me import inspect_me


CPD_SIGNATURE = b"$CPD/"
CPD_FIRST_ENTRY_OFFSET = 0x0C
CPD_IDENTIFIER_SIZE = 12
CPD_MANIFEST_FIELD_WORDS = 4
CPD_ENTRY_FIELD_WORDS = 3
CPD_MANIFEST_RECORD_SIZE = CPD_IDENTIFIER_SIZE + CPD_MANIFEST_FIELD_WORDS * 4
CPD_ENTRY_RECORD_SIZE = CPD_IDENTIFIER_SIZE + CPD_ENTRY_FIELD_WORDS * 4
MAX_MANIFEST_AREA_SIZE = 0x10000
MAX_MANIFEST_ENTRIES = 512


def _identifier(raw: bytes) -> str | None:
    """Return an ASCII identifier only when padding and bytes are safe."""

    if len(raw) != CPD_IDENTIFIER_SIZE:
        return None
    value = raw.split(b"\0", 1)[0]
    if not value or any(byte not in range(0x21, 0x7F) for byte in value):
        return None
    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return None


def _words(data: bytes, offset: int, count: int) -> list[int]:
    return [int.from_bytes(data[offset + index * 4:offset + index * 4 + 4], "little")
            for index in range(count)]


def _range_candidate(words: list[int], bound: int) -> dict | None:
    """Report an in-bounds layout candidate without naming its semantics."""

    if len(words) < 2:
        return None
    offset = words[0] & 0x00FFFFFF
    length = words[1]
    end = offset + length
    if end > bound:
        return None
    return {
        "offset_in_ftpr": offset,
        "length": length,
        "end_in_ftpr": end,
        "interpretation": (
            "layout-derived bounded range candidate; field semantics are not "
            "asserted"
        ),
    }


def parse_manifest_area(data: bytes, *, ftpr_size: int | None = None) -> dict:
    """Parse a bounded CPD manifest/metadata area from an FTPR byte slice."""

    bound = len(data) if ftpr_size is None else min(ftpr_size, len(data))
    result = {
        "signature": None,
        "signature_offset": None,
        "manifest": None,
        "metadata_entries": [],
        "warnings": [],
        "interpretation": (
            "Fixed-width CPD layout metadata only. Raw field words are "
            "reported without assigning undocumented meanings."
        ),
    }
    if bound < 0:
        result["warnings"].append("negative FTPR bound was rejected")
        return result

    signature_offset = data.find(CPD_SIGNATURE, 0, min(bound, 0x1000))
    if signature_offset < 0:
        result["warnings"].append("$CPD/ signature not found in the first 4 KiB")
        return result
    result["signature"] = CPD_SIGNATURE.decode("ascii")
    result["signature_offset"] = signature_offset

    first = signature_offset + CPD_FIRST_ENTRY_OFFSET
    if first + CPD_MANIFEST_RECORD_SIZE > bound:
        result["warnings"].append("CPD manifest record is truncated")
        return result

    manifest_name = _identifier(data[first:first + CPD_IDENTIFIER_SIZE])
    manifest_words = _words(
        data, first + CPD_IDENTIFIER_SIZE, CPD_MANIFEST_FIELD_WORDS
    )
    manifest = {
        "record_offset_in_ftpr": first,
        "record_size": CPD_MANIFEST_RECORD_SIZE,
        "identifier": manifest_name,
        "raw_field_words": manifest_words,
    }
    if manifest_name is None:
        result["warnings"].append("CPD manifest identifier is not safely printable")
        result["manifest"] = manifest
        return result
    if not manifest_name.endswith(".man"):
        result["warnings"].append("first CPD identifier does not have a .man suffix")
        result["manifest"] = manifest
        return result

    manifest_length = manifest_words[1]
    manifest_end = signature_offset + manifest_length
    if manifest_length < CPD_FIRST_ENTRY_OFFSET + CPD_MANIFEST_RECORD_SIZE:
        result["warnings"].append("declared manifest area is shorter than its header")
        result["manifest"] = manifest
        return result
    if manifest_length > MAX_MANIFEST_AREA_SIZE:
        result["warnings"].append(
            f"declared manifest area exceeds safety limit 0x{MAX_MANIFEST_AREA_SIZE:x}"
        )
        result["manifest"] = manifest
        return result
    if manifest_end > bound:
        result["warnings"].append("declared manifest area extends beyond FTPR")
        result["manifest"] = manifest
        return result

    manifest["declared_area_length"] = manifest_length
    manifest["declared_area_end_in_ftpr"] = manifest_end
    manifest["bounded_range_candidate"] = _range_candidate(manifest_words, bound)
    result["manifest"] = manifest

    position = first + CPD_MANIFEST_RECORD_SIZE
    index = 0
    while position < manifest_end:
        remaining = manifest_end - position
        if remaining < CPD_ENTRY_RECORD_SIZE:
            padding = data[position:manifest_end]
            if any(padding):
                result["warnings"].append("nonzero trailing bytes are not a full CPD entry")
            break
        raw_name = data[position:position + CPD_IDENTIFIER_SIZE]
        name = _identifier(raw_name)
        if name is None:
            result["warnings"].append(
                f"metadata entry {index} has an unsafe or non-printable identifier"
            )
            break
        fields = _words(
            data, position + CPD_IDENTIFIER_SIZE, CPD_ENTRY_FIELD_WORDS
        )
        item = {
            "index": index,
            "record_offset_in_ftpr": position,
            "record_size": CPD_ENTRY_RECORD_SIZE,
            "identifier": name,
            "raw_field_words": fields,
            "bounded_range_candidate": _range_candidate(fields, bound),
        }
        if item["bounded_range_candidate"] is None:
            result["warnings"].append(
                f"metadata entry {name} has no in-bounds range candidate"
            )
        result["metadata_entries"].append(item)
        position += CPD_ENTRY_RECORD_SIZE
        index += 1
        if index >= MAX_MANIFEST_ENTRIES:
            result["warnings"].append(
                f"metadata entry count reached safety limit {MAX_MANIFEST_ENTRIES}"
            )
            break

    result["metadata_entry_count"] = len(result["metadata_entries"])
    result["parsed_end_in_ftpr"] = position
    return result


def inspect_cpd_manifest(path: Path) -> dict:
    """Locate FTPR using existing read-only logic and inspect its CPD area."""

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
        "manifest_area": None,
        "warnings": list(me.get("warnings", [])),
    }
    if ftpr is None or ftpr.get("absolute_offset") is None:
        result["warnings"].append("FTPR partition was not identified")
        return result

    start = ftpr["absolute_offset"]
    end = start + ftpr["size"]
    if end > len(image):
        result["warnings"].append("FTPR partition extends beyond the image")
        return result
    result["manifest_area"] = parse_manifest_area(
        image[start:end], ftpr_size=ftpr["size"]
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_cpd_manifest(args.image)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
