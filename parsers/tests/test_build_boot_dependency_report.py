import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from parsers.build_boot_dependency_report import build_boot_dependency_report
from parsers.inspect_ifd import FD_SIGNATURE


def make_synthetic_image() -> bytes:
    """Build a small descriptor/FPT/FTPR/CPD image with no real firmware."""

    image = bytearray(0x210000)
    struct.pack_into("<IIII", image, 0, FD_SIGNATURE, 0x00010000, 0, 0)
    regions = [
        (0x0000, 0x0000),
        (0x0001, 0x000F),
        (0x0010, 0x01FF),
        (0x0200, 0x0201),
    ]
    for index, (base, limit) in enumerate(regions):
        struct.pack_into("<I", image, 0x10 + index * 4, (limit << 16) | base)

    me_start = 0x10000
    fpt = me_start + 0x10
    image[fpt:fpt + 4] = b"$FPT"
    struct.pack_into("<I", image, fpt + 4, 1)
    image[fpt + 8:fpt + 12] = bytes((0x20, 0x10, 0x20, 0xE0))
    entry = fpt + 0x20
    image[entry:entry + 4] = b"FTPR"
    struct.pack_into("<II", image, entry + 8, 0x100, 0x1000)

    ftpr = me_start + 0x100
    image[ftpr:ftpr + 5] = b"$CPD/"
    first = ftpr + 0x0C
    image[first:first + 12] = b"FTPRFTPR.man"
    struct.pack_into("<IIII", image, first + 12, 0, 0x58, 0x11111111, 0x22222222)

    kernel = ftpr + 0x28
    image[kernel:kernel + 12] = b"kernel" + b"\0" * 6
    struct.pack_into("<III", image, kernel + 12, 0x02000080, 0x20, 0)
    image[ftpr + 0x80:ftpr + 0xA0] = b"synthetic-runtime-data".ljust(0x20, b"\0")

    kernel_met = ftpr + 0x40
    image[kernel_met:kernel_met + 12] = b"kernel.met" + b"\0" * 2
    struct.pack_into("<III", image, kernel_met + 12, 0xA0, 0x10, 0x33333333)
    image[ftpr + 0xA0:ftpr + 0xB0] = bytes(range(0x10))
    return bytes(image)


class BuildBootDependencyReportTests(unittest.TestCase):
    def write_image(self, data: bytes) -> Path:
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "synthetic.bin"
        path.write_bytes(data)
        return path

    def test_report_contains_only_bounded_metadata(self):
        data = make_synthetic_image()
        path = self.write_image(data)

        report = build_boot_dependency_report(path)

        self.assertEqual(report["source"]["size"], len(data))
        self.assertEqual(report["source"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(report["descriptor_regions"][2]["name"], "Intel ME")
        self.assertEqual(report["fpt_partitions"][0]["name"], "FTPR")
        self.assertEqual([item["name"] for item in report["cpd_modules"]], [
            "FTPRFTPR.man", "kernel", "kernel.met",
        ])
        self.assertEqual(report["classification"]["likely_runtime_modules"], ["kernel"])
        self.assertEqual(
            report["classification"]["metadata_entries"],
            ["FTPRFTPR.man", "kernel.met"],
        )
        self.assertEqual(report["cpd_manifest"]["metadata_entries"][0]["identifier"], "kernel")
        self.assertTrue(report["unresolved_dependencies"])
        self.assertTrue(report["read_only"])

        serialized = json.dumps(report)
        for forbidden in ("raw_module_contents", "module_bytes", "firmware_bytes"):
            self.assertNotIn(forbidden, serialized)

    def test_missing_structures_remain_explicit_unknowns(self):
        path = self.write_image(b"not a firmware image")

        report = build_boot_dependency_report(path)

        self.assertEqual(report["descriptor_regions"], [])
        self.assertEqual(report["fpt_partitions"], [])
        self.assertEqual(report["cpd_modules"], [])
        kinds = {item["kind"] for item in report["unresolved_dependencies"]}
        self.assertIn("descriptor_layout", kinds)
        self.assertIn("fpt_partition_layout", kinds)
        self.assertIn("cpd_module_directory", kinds)
        self.assertIn("cpd_manifest_metadata", kinds)


if __name__ == "__main__":
    unittest.main()
