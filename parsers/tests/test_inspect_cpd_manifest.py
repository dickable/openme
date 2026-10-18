import struct
import tempfile
import unittest
from pathlib import Path

from parsers.inspect_cpd_manifest import inspect_cpd_manifest, parse_manifest_area
from parsers.inspect_ifd import FD_SIGNATURE


def make_manifest_area() -> bytes:
    data = bytearray(0x100)
    data[:5] = b"$CPD/"

    first = 0x0C
    data[first:first + 12] = b"FTPRFTPR.man"
    struct.pack_into("<IIII", data, first + 12, 0, 0x58, 0x12345678, 0x9ABCDEF0)

    second = 0x28
    data[second:second + 12] = b"kernel" + b"\0" * 6
    struct.pack_into("<III", data, second + 12, 0x02000070, 0x10, 0xDEADBEEF)

    third = 0x40
    data[third:third + 12] = b"kernel.met" + b"\0" * 2
    struct.pack_into("<III", data, third + 12, 0x90, 0x08, 0xCAFEBABE)
    return bytes(data)


class InspectCpdManifestTests(unittest.TestCase):
    def test_valid_manifest_reports_only_bounded_metadata(self):
        result = parse_manifest_area(make_manifest_area(), ftpr_size=0x100)

        self.assertEqual(result["signature"], "$CPD/")
        self.assertEqual(result["manifest"]["identifier"], "FTPRFTPR.man")
        self.assertEqual(result["manifest"]["declared_area_length"], 0x58)
        self.assertEqual(
            result["manifest"]["raw_field_words"],
            [0, 0x58, 0x12345678, 0x9ABCDEF0],
        )
        self.assertEqual(result["metadata_entry_count"], 2)
        self.assertEqual(result["metadata_entries"][0]["identifier"], "kernel")
        self.assertEqual(
            result["metadata_entries"][0]["bounded_range_candidate"],
            {
                "offset_in_ftpr": 0x70,
                "length": 0x10,
                "end_in_ftpr": 0x80,
                "interpretation": (
                    "layout-derived bounded range candidate; field semantics are "
                    "not asserted"
                ),
            },
        )
        self.assertEqual(result["warnings"], [])

    def test_invalid_identifier_is_not_trusted(self):
        data = bytearray(make_manifest_area())
        data[0x0C:0x18] = b"bad\x01name" + b"\0" * 4

        result = parse_manifest_area(bytes(data), ftpr_size=0x100)

        self.assertIsNone(result["manifest"]["identifier"])
        self.assertEqual(result["metadata_entries"], [])
        self.assertTrue(any("safely printable" in warning for warning in result["warnings"]))

    def test_manifest_boundary_must_be_in_bounds(self):
        data = bytearray(make_manifest_area())
        struct.pack_into("<I", data, 0x1C, 0x200)

        result = parse_manifest_area(bytes(data), ftpr_size=0x100)

        self.assertIsNone(result["manifest"].get("bounded_range_candidate"))
        self.assertTrue(any("beyond FTPR" in warning for warning in result["warnings"]))

    def test_missing_signature_is_safe(self):
        result = parse_manifest_area(b"\0" * 128)

        self.assertIsNone(result["manifest"])
        self.assertTrue(result["warnings"])

    def test_image_path_uses_existing_ftpr_locator(self):
        image = bytearray(0x100000)
        struct.pack_into("<IIII", image, 0, FD_SIGNATURE, 0x00010000, 0, 0)
        regions = [
            (0x0000, 0x0000),
            (0x0001, 0x004F),
            (0x0050, 0x00BF),
            (0x00C0, 0x00C2),
        ]
        for index, (base, limit) in enumerate(regions):
            struct.pack_into("<I", image, 0x10 + index * 4, (limit << 16) | base)

        me_start = 0x50000
        fpt = me_start + 0x10
        image[fpt:fpt + 4] = b"$FPT"
        struct.pack_into("<I", image, fpt + 4, 1)
        image[fpt + 8:fpt + 12] = bytes((0x20, 0x10, 0x20, 0xE0))
        entry = fpt + 0x20
        image[entry:entry + 4] = b"FTPR"
        struct.pack_into("<II", image, entry + 8, 0x100, 0x200)
        ftpr = me_start + 0x100
        image[ftpr:ftpr + len(make_manifest_area())] = make_manifest_area()

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.bin"
            path.write_bytes(image)
            result = inspect_cpd_manifest(path)

        self.assertEqual(result["manifest_area"]["manifest"]["identifier"], "FTPRFTPR.man")
        self.assertEqual(result["manifest_area"]["metadata_entry_count"], 2)


if __name__ == "__main__":
    unittest.main()
