import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_unicorn_mei_lab import main, run_lab


class UnicornMEILabTests(unittest.TestCase):
    def test_run_is_deterministic_and_echoes_synthetic_input(self):
        first = run_lab(0x20, b"hello")
        second = run_lab(0x20, b"hello")

        self.assertEqual(first, second)
        self.assertEqual(first["format"], "openme-unicorn-mei-lab-v1")
        self.assertEqual(first["input"], {
            "opcode": 0x20,
            "payload_hex": "68656c6c6f",
            "payload_length": 5,
        })
        self.assertEqual(first["completion"]["payload_hex"], "68656c6c6f")
        self.assertEqual(first["completion"]["status"], 0)
        self.assertEqual(first["response_hex"], "00000000200000000000000068656c6c6f")
        self.assertEqual(first["transport"]["interrupts"], 0)
        self.assertEqual(first["transport"]["host_to_me_count"], 0)
        self.assertEqual(first["transport"]["me_to_host_count"], 0)

    def test_cli_emits_parseable_deterministic_json(self):
        outputs = []
        for _ in range(2):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["--opcode", "7", "--payload-hex", "73616d65"]), 0)
            outputs.append(stdout.getvalue())

        self.assertEqual(outputs[0], outputs[1])
        document = json.loads(outputs[0])
        self.assertEqual(document["input"]["opcode"], 7)
        self.assertEqual(document["completion"]["payload_hex"], "73616d65")

    def test_empty_payload_is_supported(self):
        document = run_lab(0, b"")

        self.assertEqual(document["input"]["payload_hex"], "")
        self.assertEqual(document["completion"]["payload_length"], 0)

    def test_invalid_cli_payload_is_rejected(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--payload-hex", "not-hex"])

        self.assertEqual(raised.exception.code, 2)

    def test_oversized_cli_payload_returns_an_error(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = main(["--payload-hex", "00" * 57])

        self.assertEqual(result, 2)
        self.assertIn("exceeds", stderr.getvalue())

    def test_opcode_range_is_rejected_before_running(self):
        with self.assertRaises(ValueError):
            run_lab(0x100000000, b"x")


if __name__ == "__main__":
    unittest.main()
