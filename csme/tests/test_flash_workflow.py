"""Physical workflow tests; all device operations are mocked."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import flash_openme as flash
from tools.build_openme import ROOT


class FlashWorkflowTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "qemu-work/test-temp"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="flash-test-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = flash.target("test-board-rev1", "dummy", "test-chip", 4096)
        self.original = bytes(range(256)) * 16
        candidate = bytearray(self.original)
        candidate[64:68] = b"TEST"
        candidate[4095] = 0
        self.candidate = bytes(candidate)
        self.image = self.root / "candidate.bin"
        self.image.write_bytes(self.candidate)
        self.actions = []
        self.live = self.original
        owner = self

        class Device:
            def __init__(self, executable, identity, directory):
                self.directory = directory

            def operation(self, action, path):
                owner.actions.append(action)
                if action == "read":
                    path.write_bytes(owner.live)
                elif action == "write":
                    owner.live = path.read_bytes()
                elif action == "verify":
                    if owner.live != path.read_bytes():
                        raise RuntimeError("mock verification failure")

        self.backend = Device
        self.backup_dir = self.root / "backup"
        flash.backup(self.identity, self.backup_dir, backend=self.backend)
        self.actions.clear()

    def write(self, **overrides):
        opts = dict(confirm_board=self.identity["board"], confirm_sha256=flash.sha256(self.candidate),
                    recovery_note="mock recovery fixture only", execute=True, backend=self.backend)
        opts.update(overrides)
        return flash.write_image(self.backup_dir, self.image, self.root / "write", **opts)

    def test_plan_is_offline_and_reports_exact_ranges(self):
        report, _ = flash.prepare(self.backup_dir, self.image)
        self.assertEqual(report["changed_bytes"], 5)
        self.assertEqual([(r["start"], r["end_exclusive"]) for r in report["ranges"]], [(64, 68), (4095, 4096)])
        self.assertEqual(self.actions, [])

    def test_write_order_and_readback(self):
        report = self.write()
        self.assertEqual(self.actions, ["read", "write", "verify", "read"])
        self.assertTrue(report["verified"])
        self.assertEqual(report["readback_sha256"], flash.sha256(self.candidate))
        self.assertEqual((self.backup_dir / "read-1.bin").read_bytes(), self.original)

    def test_confirmation_required_before_hardware_access(self):
        for override in ({"execute": False}, {"confirm_board": "different-board"},
                         {"confirm_sha256": "0" * 64}, {"recovery_note": ""}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.write(**override)
            self.assertEqual(self.actions, [])

    def test_changed_live_chip_stops_before_write(self):
        self.live = self.candidate
        with self.assertRaisesRegex(ValueError, "live chip differs"):
            self.write()
        self.assertEqual(self.actions, ["read"])
        result = json.loads((self.root / "write/result.json").read_text())
        self.assertFalse(result["verified"])
        self.assertEqual(result["phase"], "prewrite")

    def test_tampered_backup_stops_before_hardware_access(self):
        (self.backup_dir / "read-2.bin").write_bytes(self.candidate)
        with self.assertRaisesRegex(ValueError, "backup files"):
            self.write()
        self.assertEqual(self.actions, [])

    def test_wrong_image_size_and_qemu_image_rejected(self):
        self.image.write_bytes(b"short")
        with self.assertRaises(ValueError):
            flash.prepare(self.backup_dir, self.image)
        self.image.write_bytes(b"\x02\xb0\xad\x1b" + self.candidate[4:])
        with self.assertRaisesRegex(ValueError, "QEMU image"):
            flash.prepare(self.backup_dir, self.image)

    def test_identical_image_needs_no_write(self):
        self.image.write_bytes(self.original)
        with self.assertRaisesRegex(ValueError, "no write is needed"):
            self.write()
        self.assertEqual(self.actions, [])

    def test_existing_session_never_overwritten(self):
        self.write()
        self.actions.clear()
        with self.assertRaises(FileExistsError):
            self.write()
        self.assertEqual(self.actions, [])

    def test_readback_mismatch_is_not_success(self):
        owner = self

        class BadReadback(self.backend):
            def operation(self, action, path):
                super().operation(action, path)
                if path.name == "readback.bin":
                    path.write_bytes(owner.original)

        with self.assertRaisesRegex(ValueError, "post-write readback differs"):
            self.write(backend=BadReadback)
        result = json.loads((self.root / "write/result.json").read_text())
        self.assertFalse(result["verified"])
        self.assertEqual(result["phase"], "readback")

    def test_write_error_retained_without_retry(self):
        owner = self

        class FailWrite(self.backend):
            def operation(self, action, path):
                if action == "write":
                    owner.actions.append(action)
                    raise RuntimeError("mock programmer failure")
                super().operation(action, path)

        with self.assertRaises(RuntimeError):
            self.write(backend=FailWrite)
        self.assertEqual(self.actions, ["read", "write"])
        result = json.loads((self.root / "write/result.json").read_text())
        self.assertEqual(result["phase"], "write-started")
        self.assertFalse(result["verified"])
        self.assertTrue((self.root / "write/prewrite.bin").exists())

    def test_independent_read_disagreement_retains_both(self):
        owner = self

        class Unstable(self.backend):
            def operation(self, action, path):
                super().operation(action, path)
                owner.live = owner.candidate

        dest = self.root / "unstable"
        with self.assertRaisesRegex(ValueError, "independent reads disagree"):
            flash.backup(self.identity, dest, backend=Unstable)
        self.assertTrue((dest / "read-1.bin").exists())
        self.assertTrue((dest / "read-2.bin").exists())
        self.assertFalse((dest / "backup.json").exists())

    def test_uniform_read_is_not_verified(self):
        self.live = b"\xff" * 4096
        with self.assertRaisesRegex(ValueError, "uniform flash"):
            flash.backup(self.identity, self.root / "uniform", backend=self.backend)

    def test_generic_board_and_force_overrides_rejected(self):
        for board in ("Skylake", "all", "unknown", "../bad"):
            with self.subTest(board=board), self.assertRaises(ValueError):
                flash.target(board, "internal", "chip", 4096)
        for programmer in ("internal:laptop=force_I_want_a_brick", "-x", "dummy;bad"):
            with self.subTest(programmer=programmer), self.assertRaises(ValueError):
                flash.target("board-rev1", programmer, "chip", 4096)

    def test_exact_argv_keeps_verification_and_no_shell(self):
        logdir = self.root / "logs"
        logdir.mkdir()
        device = flash.Flashrom("flashrom", self.identity, logdir)
        with patch.object(flash.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            device.operation("write", self.image)
        argv = run.call_args.args[0]
        self.assertEqual(argv, ["flashrom", "-p", "dummy", "-c", "test-chip", "--write", str(self.image)])
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertNotIn("timeout", run.call_args.kwargs)
        self.assertNotIn("--noverify", argv)

    def test_difference_report_bounded(self):
        before = bytes(4096)
        after = bytes(i % 2 for i in range(4096))
        report = flash.differences(before, after)
        self.assertEqual(report["range_count"], 2048)
        self.assertEqual(len(report["ranges"]), 256)
        self.assertTrue(report["ranges_truncated"])


if __name__ == "__main__":
    unittest.main()
