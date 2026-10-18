import unittest
from pathlib import Path

from parsers.inspect_image import ImageError, inspect_image

FIXTURES = Path(__file__).parent / "fixtures"


class InspectImageTests(unittest.TestCase):
    def test_valid_image(self):
        result = inspect_image(FIXTURES / "valid.bin")
        self.assertEqual(result["size"], 256)
        self.assertEqual([r["name"] for r in result["regions"]], ["BIOS", "ME!!", "GBE!"])
        self.assertEqual(result["warnings"], [])
        self.assertTrue(all(r["sha256"] for r in result["regions"]))

    def test_truncated_image(self):
        with self.assertRaisesRegex(ImageError, "truncated"):
            inspect_image(FIXTURES / "truncated.bin")

    def test_bad_magic(self):
        with self.assertRaisesRegex(ImageError, "invalid magic"):
            inspect_image(FIXTURES / "bad_magic.bin")

    def test_overlap_warning(self):
        result = inspect_image(FIXTURES / "overlap.bin")
        self.assertTrue(any("overlap" in warning for warning in result["warnings"]))

    def test_out_of_bounds_warning(self):
        result = inspect_image(FIXTURES / "out_of_bounds.bin")
        self.assertTrue(any("beyond the image" in warning for warning in result["warnings"]))
        self.assertIsNone(result["regions"][0]["sha256"])

    def test_missing_file(self):
        with self.assertRaisesRegex(ImageError, "cannot read image"):
            inspect_image(FIXTURES / "missing.bin")


if __name__ == "__main__":
    unittest.main()

