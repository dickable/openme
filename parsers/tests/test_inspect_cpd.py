import struct
import unittest

from parsers.inspect_cpd import parse_cpd_directory


class InspectCpdTests(unittest.TestCase):
    def test_manifest_and_regular_entries(self):
        image = bytearray(0x200)
        image[:5] = b"$CPD/"

        first = 0x0C
        image[first:first + 12] = b"FTPRFTPR.man"
        struct.pack_into("<III", image, first + 12, 0, 0x28, 0x1234)

        second = 0x28
        image[second:second + 12] = b"kernel" + b"\0" * 6
        struct.pack_into("<III", image, second + 12, 0x02000040, 0x30, 0)
        image[0x40:0x70] = bytes(range(0x30))

        third = 0x40
        image[third:third + 12] = b"kernel.met" + b"\0" * 2
        struct.pack_into("<III", image, third + 12, 0x90, 0x10, 0)

        result = parse_cpd_directory(bytes(image))
        self.assertEqual(result["entry_count"], 3)
        self.assertEqual(result["entries"][0]["name"], "FTPRFTPR.man")
        self.assertEqual(result["entries"][1]["name"], "kernel")
        self.assertEqual(result["entries"][1]["offset_in_partition"], 0x40)
        self.assertEqual(result["entries"][1]["flags"], 0x02)
        self.assertEqual(result["entries"][1]["size"], 0x30)
        self.assertEqual(result["warnings"], [])

    def test_missing_signature_is_safe(self):
        result = parse_cpd_directory(b"\0" * 128)
        self.assertEqual(result["entries"], [])
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
