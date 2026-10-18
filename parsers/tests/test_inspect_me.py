import struct
import tempfile
import unittest
from pathlib import Path

from parsers.inspect_me import inspect_me


class InspectMeTests(unittest.TestCase):
    def test_fpt_partitions_are_reported(self):
        image = bytearray(0x20000)
        struct.pack_into("<IIII", image, 0x10, 0x0FF0A55A,
                         0x00040000, 0, 0)
        struct.pack_into("<I", image, 0x40, 0)
        struct.pack_into("<I", image, 0x44, (0x000F << 16) | 0x0001)
        struct.pack_into("<I", image, 0x48, (0x001F << 16) | 0x0010)
        me_start = 0x10000
        fpt = me_start + 0x10
        image[fpt:fpt + 4] = b"$FPT"
        struct.pack_into("<I", image, fpt + 4, 2)
        image[fpt + 8:fpt + 12] = bytes((0x20, 0x10, 0x20, 0xE0))
        entry = fpt + 0x20
        image[entry:entry + 4] = b"FTPR"
        struct.pack_into("<II", image, entry + 8, 0x100, 0x200)
        image[entry + 0x20:entry + 0x24] = b"FTUP"
        struct.pack_into("<II", image, entry + 0x28, 0x300, 0x100)
        image[me_start + 0x100:me_start + 0x104] = b"$MN2"
        struct.pack_into("<HHHH", image, me_start + 0x108, 11, 8, 92, 4222)

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "me.bin"
            path.write_bytes(image)
            result = inspect_me(path)
        self.assertEqual(result["fpt"]["partition_count"], 2)
        self.assertEqual(result["fpt"]["partitions"][0]["name"], "FTPR")
        self.assertEqual(result["fpt"]["partitions"][1]["name"], "FTUP")
        self.assertEqual(result["mn2_headers"][0]["candidate_16bit_tuple"], [11, 8, 92, 4222])
        self.assertIn("not asserted", result["version_status"])


if __name__ == "__main__":
    unittest.main()
