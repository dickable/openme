"""Read-only inspector for the OpenME synthetic image format."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

MAGIC = b"OMES"
HEADER_SIZE = 8
ENTRY_SIZE = 16


class ImageError(Exception):
    """Raised when an image cannot be parsed safely."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_image(path: Path) -> dict:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ImageError(f"cannot read image: {exc}") from exc

    result = {
        "path": str(path),
        "size": len(data),
        "sha256": sha256(data),
        "regions": [],
        "warnings": [],
    }

    if len(data) < HEADER_SIZE:
        raise ImageError("image is truncated before the header")
    if data[:4] != MAGIC:
        raise ImageError("invalid magic; expected OMES")

    (count,) = struct.unpack_from("<I", data, 4)
    table_end = HEADER_SIZE + count * ENTRY_SIZE
    if table_end > len(data):
        raise ImageError("image is truncated before the region table ends")

    ranges = []
    for index in range(count):
        start = HEADER_SIZE + index * ENTRY_SIZE
        raw_name, offset, size, reserved = struct.unpack_from("<4sIII", data, start)
        name = raw_name.rstrip(b"\0").decode("ascii", errors="replace")
        if reserved != 0:
            result["warnings"].append(f"region {index} ({name}) has non-zero reserved bytes")
        end = offset + size
        if end > len(data):
            result["warnings"].append(f"region {index} ({name}) extends beyond the image")
            region_hash = None
        else:
            region_hash = sha256(data[offset:end])
            ranges.append((offset, end, index, name))
        result["regions"].append({
            "name": name,
            "offset": offset,
            "size": size,
            "end": end,
            "sha256": region_hash,
        })

    for left, right in enumerate(ranges):
        for other in ranges[left + 1 :]:
            if right[0] < other[1] and other[0] < right[1]:
                result["warnings"].append(
                    f"regions {right[2]} ({right[3]}) and {other[2]} ({other[3]}) overlap"
                )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_image(args.image)
    except ImageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2 if "cannot read image" in str(exc) else 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

