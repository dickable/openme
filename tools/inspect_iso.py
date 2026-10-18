"""Read-only ISO9660 metadata inspector; never mounts or extracts an image."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import struct
import sys
from pathlib import Path

SECTOR = 2048
PVD_SECTOR = 16
MAX_DIRECTORY_ENTRIES = 10000


def _both_endian_u16(data: bytes, offset: int) -> tuple[int, bool]:
    little = struct.unpack_from("<H", data, offset)[0]
    big = struct.unpack_from(">H", data, offset + 2)[0]
    return little, little == big


def _both_endian_u32(data: bytes, offset: int) -> tuple[int, bool]:
    little = struct.unpack_from("<I", data, offset)[0]
    big = struct.unpack_from(">I", data, offset + 4)[0]
    return little, little == big


def _read_directory(data: bytes, extent: int, size: int, block_size: int, prefix: str,
                    files: list[dict], warnings: list[str], visited: set[tuple[int, int]]) -> None:
    key = (extent, size)
    if key in visited:
        warnings.append(f"directory {prefix or '/'} is referenced more than once")
        return
    visited.add(key)

    start = extent * block_size
    end = start + size
    if start < 0 or start > len(data) or end > len(data):
        warnings.append(f"directory {prefix or '/'} extends beyond the image")
        return

    directory = data[start:end]
    cursor = 0
    while cursor < len(directory):
        record_length = directory[cursor]
        if record_length == 0:
            cursor = ((cursor // block_size) + 1) * block_size
            continue
        if record_length < 34 or cursor + record_length > len(directory):
            warnings.append(f"malformed directory record at byte {start + cursor}")
            return
        entry = directory[cursor:cursor + record_length]
        name_length = entry[32]
        if 33 + name_length > len(entry):
            warnings.append(f"directory record at byte {start + cursor} has an invalid name length")
            return
        name_bytes = entry[33:33 + name_length]
        if name_bytes not in (b"\x00", b"\x01"):
            name = name_bytes.decode("ascii", "replace")
            if ";1" in name:
                name = name.rsplit(";1", 1)[0]
            child_extent, extent_ok = _both_endian_u32(entry, 2)
            child_size, size_ok = _both_endian_u32(entry, 10)
            if not extent_ok or not size_ok:
                warnings.append(f"directory record for {name} has mismatched endian fields")
            is_directory = bool(entry[25] & 2)
            child_path = f"{prefix}/{name}" if prefix else f"/{name}"
            item = {"name": name, "path": child_path, "extent": child_extent,
                    "size": child_size, "directory": is_directory}
            files.append(item)
            if len(files) >= MAX_DIRECTORY_ENTRIES:
                warnings.append(f"directory entry limit ({MAX_DIRECTORY_ENTRIES}) reached")
                return
            if is_directory:
                _read_directory(data, child_extent, child_size, block_size, child_path,
                                files, warnings, visited)
        cursor += record_length


def _inspect_el_torito(data: bytes) -> dict | None:
    """Read El Torito boot-record/catalog metadata without reading boot files."""

    offset = 17 * SECTOR
    if len(data) < offset + SECTOR:
        return None
    descriptor = data[offset:offset + SECTOR]
    if descriptor[0] != 0 or descriptor[1:6] != b"CD001" or descriptor[7:39] != b"EL TORITO SPECIFICATION".ljust(32, b"\0"):
        return None
    catalog_lba = struct.unpack_from("<I", descriptor, 71)[0]
    catalog_offset = catalog_lba * SECTOR
    result = {"catalog_lba": catalog_lba}
    if catalog_offset + 64 > len(data):
        result["warnings"] = ["El Torito boot catalog extends beyond the image"]
        return result
    catalog = data[catalog_offset:catalog_offset + 64]
    result["validation_header"] = {
        "header_id": catalog[0],
        "platform_id": catalog[1],
        "manufacturer": catalog[4:28].rstrip(b" \0").decode("ascii", "replace"),
        "checksum_valid": sum(struct.unpack_from("<16H", catalog, 0)) % 0x10000 == 0,
    }
    entry = catalog[32:64]
    sector_count = struct.unpack_from("<H", entry, 6)[0]
    image_lba = struct.unpack_from("<I", entry, 8)[0]
    result["default_entry"] = {
        "boot_indicator": entry[0],
        "bootable": entry[0] == 0x88,
        "media_type": entry[1],
        "load_segment": struct.unpack_from("<H", entry, 2)[0],
        "sector_count": sector_count,
        "image_lba": image_lba,
        "image_size_bytes": sector_count * 512,
    }
    return result


def inspect_iso(path: Path) -> dict:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read ISO: {exc}") from exc
    result = {"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    warnings = []
    offset = PVD_SECTOR * SECTOR
    if len(data) < offset + SECTOR:
        result["format"] = "unknown"
        result["warnings"] = ["too small for an ISO9660 primary volume descriptor"]
        return result
    pvd = data[offset : offset + SECTOR]
    if pvd[0] != 1 or pvd[1:6] != b"CD001" or pvd[6] != 1:
        result["format"] = "unknown"
        result["warnings"] = ["ISO9660 primary volume descriptor not found"]
        return result
    volume_space_size, volume_ok = _both_endian_u32(pvd, 80)
    block_size, block_ok = _both_endian_u16(pvd, 128)
    if not volume_ok:
        warnings.append("volume space size has mismatched endian fields")
    if not block_ok:
        warnings.append("logical block size has mismatched endian fields")
    if block_size == 0:
        result["format"] = "unknown"
        result["warnings"] = warnings + ["logical block size is zero"]
        return result
    result.update({
        "format": "ISO9660",
        "system_id": pvd[8:40].rstrip(b" ").decode("ascii", "replace"),
        "volume_id": pvd[40:72].rstrip(b" ").decode("ascii", "replace"),
        "volume_space_size": volume_space_size,
        "logical_block_size": block_size,
    })
    boot = _inspect_el_torito(data)
    if boot is not None:
        result["el_torito"] = boot
    root = pvd[156:190]
    if len(root) < 34 or root[0] < 34:
        result["warnings"] = warnings + ["root directory record is malformed"]
        result["root_entries"] = []
        result["files"] = []
        return result
    root_extent, root_extent_ok = _both_endian_u32(root, 2)
    root_size, root_size_ok = _both_endian_u32(root, 10)
    if not root_extent_ok or not root_size_ok:
        warnings.append("root directory record has mismatched endian fields")
    result["root_extent"] = root_extent
    result["root_size"] = root_size
    files = []
    _read_directory(data, root_extent, root_size, block_size, "", files, warnings, set())
    result["files"] = files
    result["root_entries"] = [item for item in files if item["path"].count("/") == 1]
    regular_files = [item for item in files if not item["directory"]]
    extension_counts = Counter()
    candidates = []
    candidate_extensions = {
        ".bin", ".cap", ".fd", ".fl1", ".fl2", ".fw", ".rom", ".wph",
    }
    for item in regular_files:
        name = item["name"]
        suffix = Path(name).suffix.lower()
        extension_counts[suffix or "[none]"] += 1
        if suffix in candidate_extensions:
            candidates.append({
                "path": item["path"],
                "size": item["size"],
                "reason": f"firmware-like extension {suffix}",
            })
    result["file_count"] = len(regular_files)
    result["directory_count"] = sum(1 for item in files if item["directory"])
    result["extension_counts"] = dict(sorted(extension_counts.items()))
    result["candidate_payloads"] = candidates
    if boot and "default_entry" in boot:
        entry = boot["default_entry"]
        candidates.append({
            "path": "[El Torito default boot image]",
            "extent": entry["image_lba"],
            "size": entry["image_size_bytes"],
            "reason": "boot-catalog image; contents not read",
        })
    result["handling"] = (
        "Metadata-only inspection; file contents are not extracted, mounted, "
        "executed, or modified."
    )
    result["warnings"] = warnings
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_iso(args.image)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, indent=2, sort_keys=True))

