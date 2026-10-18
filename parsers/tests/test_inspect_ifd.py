import struct
import tempfile
import unittest
from pathlib import Path

from parsers.inspect_ifd import FD_SIGNATURE, inspect_ifd


class InspectIfdTests(unittest.TestCase):
    def make_image(self, *, truncated=False):
        image = bytearray(0x10000)
        struct.pack_into("<IIII", image, 0, FD_SIGNATURE, 0x00010000, 0, 0)
        # FRBA = 0x10. Descriptor, BIOS, ME, and GbE regions.
        regions = [(0x0000, 0x0000), (0x0001, 0x004F), (0x0050, 0x00BF), (0x00C0, 0x00C2)]
        for index, (base, limit) in enumerate(regions):
            struct.pack_into("<I", image, 0x10 + index * 4, (limit << 16) | base)
        if truncated:
            return bytes(image[:0x800])
        return bytes(image)

    def test_regions_are_decoded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.bin"
            path.write_bytes(self.make_image())
            result = inspect_ifd(path)
        self.assertEqual(result["descriptor"]["region_table_offset"], 0x10)
        self.assertEqual(result["regions"][1]["name"], "BIOS")
        self.assertEqual(result["regions"][1]["offset"], 0x1000)
        self.assertEqual(result["regions"][1]["end"], 0x4FFFF)

    def test_missing_descriptor_is_reported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.bin"
            path.write_bytes(b"not a flash image")
            result = inspect_ifd(path)
        self.assertIsNone(result["descriptor"])
        self.assertTrue(result["warnings"])

    def test_truncated_descriptor_is_reported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.bin"
            path.write_bytes(self.make_image(truncated=True))
            result = inspect_ifd(path)
        self.assertIsNone(result["descriptor"])
        self.assertIn("truncated", result["warnings"][0])

    def test_invalid_region_table_offset_is_reported(self):
        image = bytearray(self.make_image())
        # FRBA points beyond the descriptor, so no region table is trusted.
        struct.pack_into("<I", image, 4, 0x00FF0000)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.bin"
            path.write_bytes(image)
            result = inspect_ifd(path)
        self.assertEqual(result["regions"], [])
        self.assertIn("outside the 4 KiB descriptor", result["warnings"][0])

    def test_signature_offset_is_not_used_as_descriptor_base(self):
        image = bytearray(0x10000)
        struct.pack_into("<IIII", image, 0x10, FD_SIGNATURE,
                         0x00040000, 0, 0)
        struct.pack_into("<I", image, 0x40, 0x00000000)
        struct.pack_into("<I", image, 0x44, (0x000F << 16) | 0x0001)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "offset.bin"
            path.write_bytes(image)
            result = inspect_ifd(path)
        self.assertEqual(result["descriptor"]["base"], 0)
        self.assertEqual(result["descriptor"]["region_table_offset"], 0x40)
        self.assertEqual(result["regions"][1]["offset"], 0x1000)

    def test_common_unused_region_sentinels_are_not_regions(self):
        image = bytearray(self.make_image())
        struct.pack_into("<I", image, 0x20, 0x00007FFF)
        struct.pack_into("<I", image, 0x24, 0xFFFFFFFF)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "unused.bin"
            path.write_bytes(image)
            result = inspect_ifd(path)
        self.assertEqual(result["regions"][4]["size"], 0)
        self.assertIsNone(result["regions"][4]["offset"])
        self.assertEqual(result["regions"][5]["size"], 0)
        self.assertIsNone(result["regions"][5]["offset"])

    def test_overlapping_regions_are_reported(self):
        image = bytearray(self.make_image())
        image.extend(b"\0" * (0x50000 - len(image)))
        # Make the ME region start inside the BIOS region.
        struct.pack_into("<I", image, 0x18, (0x004F << 16) | 0x0002)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "image.bin"
            path.write_bytes(image)
            result = inspect_ifd(path)
        self.assertTrue(any("overlap" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()

