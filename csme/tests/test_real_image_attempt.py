import unittest
from pathlib import Path

from csme.runtime.real_image_attempt import (
    AttemptStatus,
    RealMEImageAttempt,
)


class RealMEImageAttemptTests(unittest.TestCase):
    def test_missing_image_is_reported_without_execution(self):
        report = RealMEImageAttempt(Path("does-not-exist.bin")).run()
        self.assertEqual(report["status"], AttemptStatus.PRECHECK_FAILED.value)
        self.assertFalse(report["execution"]["instruction_execution_attempted"])
        self.assertEqual(report["execution"]["bytes_executed"], 0)

    def test_non_spi_image_stops_at_preflight(self):
        path = Path(__file__).with_name("_not_an_spi_image.bin")
        try:
            path.write_bytes(b"OpenME test input")
            report = RealMEImageAttempt(path).run()
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(report["status"], AttemptStatus.PRECHECK_FAILED.value)
        self.assertFalse(report["execution"]["instruction_execution_attempted"])
        self.assertEqual(report["execution"]["bytes_executed"], 0)


if __name__ == "__main__":
    unittest.main()
