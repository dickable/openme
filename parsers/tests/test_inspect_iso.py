import struct
import tempfile
import unittest
from pathlib import Path

from tools.inspect_iso import inspect_iso


SECTOR = 2048


def both_endian_u16(value: int) -> bytes:
    return struct.pack("<H", value) + struct.pack(">H", value)


def both_endian_u32(value: int) -> bytes:
    return struct.pack("<I", value) + struct.pack(">I", value)


def directory_record(name: bytes, extent: int, size: int, *, directory: bool = False) -> bytes:
    record_size = 33 + len(name)
    if record_size % 2:
        record_size += 1
    record = bytearray(record_size)
    record[0] = record_size
    record[2:10] = both_endian_u32(extent)
    record[10:18] = both_endian_u32(size)
    record[25] = 2 if directory else 0
    record[28:32] = both_endian_u16(1)
    record[32] = len(name)
    record[33:33 + len(name)] = name
    return bytes(record)


def make_iso() -> bytes:
    image = bytearray(24 * SECTOR)
    pvd_offset = 16 * SECTOR
    pvd = memoryview(image)[pvd_offset:pvd_offset + SECTOR]
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[40:72] = b"OPENME TEST".ljust(32, b" ")
    pvd[80:88] = both_endian_u32(24)
    pvd[128:132] = both_endian_u16(SECTOR)
    pvd[156:190] = directory_record(b"\x00", 20, SECTOR, directory=True)

    root = memoryview(image)[20 * SECTOR:21 * SECTOR]
    entries = [
        directory_record(b"\x00", 20, SECTOR, directory=True),
        directory_record(b"\x01", 20, SECTOR, directory=True),
        directory_record(b"README.TXT;1", 21, 5),
    ]
    cursor = 0
    for entry in entries:
        root[cursor:cursor + len(entry)] = entry
        cursor += len(entry)
    image[21 * SECTOR:21 * SECTOR + 5] = b"hello"
    return bytes(image)


def make_bootable_iso() -> bytes:
    image = bytearray(make_iso())
    boot_record = memoryview(image)[17 * SECTOR:18 * SECTOR]
    boot_record[0] = 0
    boot_record[1:6] = b"CD001"
    boot_record[6] = 1
    boot_record[7:39] = b"EL TORITO SPECIFICATION".ljust(32, b"\0")
    boot_record[71:75] = struct.pack("<I", 22)
    catalog = memoryview(image)[22 * SECTOR:23 * SECTOR]
    catalog[0] = 1
    catalog[1] = 0
    catalog[4:28] = b"OPENME TEST".ljust(24, b" ")
    catalog[28:32] = b"\0\0\x55\xaa"
    catalog[32] = 0x88
    catalog[33] = 4
    catalog[40:42] = struct.pack("<H", 27)
    catalog[40:44] = struct.pack("<I", 23)
    return bytes(image)


class InspectIsoTests(unittest.TestCase):
    def test_metadata_and_root_file_are_reported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.iso"
            path.write_bytes(make_iso())
            result = inspect_iso(path)
        self.assertEqual(result["format"], "ISO9660")
        self.assertEqual(result["volume_id"], "OPENME TEST")
        self.assertEqual(result["root_entries"][0]["name"], "README.TXT")
        self.assertEqual(result["files"][0]["path"], "/README.TXT")
        self.assertEqual(result["files"][0]["size"], 5)
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["directory_count"], 0)
        self.assertEqual(result["candidate_payloads"], [])
        self.assertEqual(result["warnings"], [])

    def test_invalid_root_bounds_are_reported(self):
        image = bytearray(make_iso())
        struct.pack_into("<I", image, 16 * SECTOR + 158, 0xFFFF)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.iso"
            path.write_bytes(image)
            result = inspect_iso(path)
        self.assertTrue(any("extends beyond" in warning for warning in result["warnings"]))

    def test_el_torito_metadata_is_reported_without_extraction(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "bootable.iso"
            path.write_bytes(make_bootable_iso())
            result = inspect_iso(path)
        self.assertEqual(result["el_torito"]["catalog_lba"], 22)
        entry = result["el_torito"]["default_entry"]
        self.assertTrue(entry["bootable"])
        self.assertEqual(entry["image_lba"], 23)
        self.assertEqual(result["candidate_payloads"][-1]["path"],
                         "[El Torito default boot image]")


if __name__ == "__main__":
    unittest.main()
