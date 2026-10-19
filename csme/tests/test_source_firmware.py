"""Source firmware format tests and native C regression harnesses."""
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from tools.build_openme import ROOT, find_tool, inspect_image
from tools.run_openme_qemu import command


def fixture():
    return struct.pack("<8I", 0x1badb002, 0x10000, (-0x1baeb002) & 0xffffffff,
                       0x100000, 0x100000, 0x100040, 0x104040, 0x100020) + bytes(32)


class SourceImageTests(unittest.TestCase):
    def test_valid_extent_is_not_bss_capacity(self):
        info = inspect_image(fixture())
        self.assertEqual(info["bytes"], 64)
        self.assertEqual(info["bss_end"] - info["load_base"], 0x4040)
        self.assertFalse(info["physical_flash_image"])

    def test_short_or_trailing_data_rejected(self):
        for data in (b"", fixture()[:31], fixture()[:-1], fixture() + b"x"):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                inspect_image(data)

    def test_corrupted_header_rejected(self):
        for word, value in ((0, 0), (1, 0), (2, 0), (3, 0), (4, 0),
                            (5, 0), (6, 0x100010), (6, 0x200000),
                            (7, 0x100000), (7, 0x100040), (7, 0x104000)):
            data = bytearray(fixture())
            struct.pack_into("<I", data, word * 4, value)
            with self.subTest(word=word, value=value), self.assertRaises(ValueError):
                inspect_image(data)

    def test_qemu_plan_has_no_physical_drive_or_vendor_image(self):
        argv = command(Path("qemu"), Path("openme-qemu.bin"), None,
                       ["-serial", "stdio"], Path("trace.log"))
        self.assertIn("-nodefaults", argv)
        self.assertIn("pc,accel=tcg", argv)
        self.assertNotIn("-no-shutdown", argv)
        self.assertNotIn("-drive", argv)
        self.assertNotIn("openme-me", " ".join(argv))
        interactive = command(Path("qemu"), Path("openme-qemu.bin"), None,
                              ["-serial", "stdio"], Path("trace.log"), execution_trace=False)
        self.assertEqual(interactive[interactive.index("-d") + 1], "in_asm")


class NativeFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.gcc = find_tool("gcc")
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))

    def compile_and_run(self, sources):
        env = dict(os.environ, PATH=str(Path(self.gcc).parent) + os.pathsep + os.environ.get("PATH", ""))
        scratch = ROOT / "qemu-work" / "test-temp"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="openme-c-test-", dir=scratch) as temp:
            env.update(TEMP=temp, TMP=temp, TMPDIR=temp)
            exe = str(Path(temp) / ("test.exe" if os.name == "nt" else "test"))
            argv = [self.gcc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", *sources, "-o", exe]
            compiled = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([exe], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_c_core(self):
        output = self.compile_and_run(["src/core.c", "csme/tests/test_openme_core.c"])
        self.assertIn("10000 malformed cases passed", output)

    def test_c_heci(self):
        output = self.compile_and_run(["src/mei/heci.c", "csme/tests/test_openme_heci.c"])
        self.assertIn("10000 malformed cases passed", output)

    def test_c_persistence(self):
        output = self.compile_and_run([
            "src/fs/flashfs.c", "src/fs/nor_model.c", "src/firmware.c",
            "src/mei/heci.c", "src/service/echo.c", "src/hal/model/model_hal.c",
            "src/platform/support.c", "csme/tests/test_openme_persistence.c"])
        self.assertIn("failed-save regressions passed", output)

    def test_existing_c_platform(self):
        self.compile_and_run(["csme/bootloader/openme_me_platform.c", "csme/tests/test_openme_me_platform.c"])


if __name__ == "__main__":
    unittest.main()
