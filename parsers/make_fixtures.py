"""Generate deterministic synthetic images used by parser tests."""

from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).parent / "tests" / "fixtures"


def image(regions, *, magic=b"OMES", reserved=0, truncate=None):
    table = bytearray(magic + struct.pack("<I", len(regions)))
    for name, offset, size in regions:
        table.extend(struct.pack("<4sIII", name.encode("ascii"), offset, size, reserved))
    data = bytearray(max(256, len(table)))
    data[: len(table)] = table
    for name, offset, size in regions:
        if offset + size <= len(data):
            data[offset : offset + size] = (name.encode("ascii") * (size // 4 + 1))[:size]
    return bytes(data if truncate is None else data[:truncate])


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    valid = [("BIOS", 64, 96), ("ME!!", 160, 48), ("GBE!", 208, 32)]
    fixtures = {
        "valid.bin": image(valid),
        "truncated.bin": image(valid, truncate=10),
        "bad_magic.bin": image(valid, magic=b"NOPE"),
        "overlap.bin": image([("BIOS", 64, 96), ("ME!!", 120, 48)]),
        "out_of_bounds.bin": image([("BIOS", 240, 64)]),
    }
    for name, contents in fixtures.items():
        (ROOT / name).write_bytes(contents)


if __name__ == "__main__":
    main()

