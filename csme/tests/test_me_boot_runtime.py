import unittest
from csme.runtime.me_boot_runtime import (
    BootPhase,
    BootRuntimeError,
    SyntheticMERuntime,
)


class SyntheticMERuntimeTests(unittest.TestCase):
    def test_boot_runs_all_phases_and_loads_services(self):
        runtime = SyntheticMERuntime()
        state = runtime.boot()
        self.assertEqual(runtime.phase, BootPhase.RUNNING)
        self.assertEqual(state["platform"], "openme-synthetic-skylake")
        self.assertIn("heci", state["services"])
        self.assertIn("kernel", state["loaded_modules"])
        self.assertGreaterEqual(state["event_count"], 6)

    def test_filesystem_is_available_only_after_boot(self):
        runtime = SyntheticMERuntime()
        with self.assertRaises(BootRuntimeError):
            runtime.list_dir("/")
        runtime.boot()
        self.assertIn("etc", runtime.list_dir("/"))
        self.assertIn("platform", runtime.list_dir("/etc/openme"))
        self.assertEqual(
            runtime.read_file("/etc/openme/platform"),
            b"openme-synthetic-skylake\n",
        )

    def test_power_cycle_updates_state_and_log(self):
        runtime = SyntheticMERuntime()
        runtime.boot()
        runtime.suspend()
        self.assertEqual(runtime.phase, BootPhase.SUSPENDED)
        runtime.resume()
        self.assertEqual(runtime.phase, BootPhase.RUNNING)
        log = runtime.read_file("/var/log/boot").decode("ascii")
        self.assertIn("power state suspended", log)
        self.assertIn("power state resumed", log)

    def test_unsupported_platform_fails_without_loading_modules(self):
        runtime = SyntheticMERuntime()
        runtime.manifest = type(runtime.manifest)(platform="other")
        with self.assertRaises(BootRuntimeError):
            runtime.boot()
        self.assertEqual(runtime.phase, BootPhase.FAILED)
        self.assertEqual(runtime.loaded_modules, [])


if __name__ == "__main__":
    unittest.main()
