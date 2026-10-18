import unittest

from csme.cpu.unicorn_runtime import (
    UNICORN_AVAILABLE,
    UnicornRuntime,
    UnicornUnavailableError,
    synthetic_sum_program,
)


@unittest.skipUnless(UNICORN_AVAILABLE, "optional Unicorn Python package is not installed")
class UnicornRuntimeTests(unittest.TestCase):
    def test_synthetic_program_is_deterministic(self):
        first = UnicornRuntime()
        second = UnicornRuntime()
        for runtime in (first, second):
            runtime.load_synthetic_code(synthetic_sum_program())
            runtime.run()
        self.assertEqual(first.registers(), second.registers())
        self.assertEqual(first.read_memory(0x2000, 4), b"xV4\x12")
        self.assertEqual(first.registers()["eax"], 0x2468ACF0)

    def test_instruction_and_memory_traces_are_exposed(self):
        runtime = UnicornRuntime()
        seen = []
        runtime.add_trace_listener(lambda kind, event: seen.append((kind, event)))
        runtime.load_synthetic_code(synthetic_sum_program())
        runtime.run()
        self.assertGreaterEqual(len(runtime.instructions), 5)
        self.assertTrue(any(event.address == 0x1000 for event in runtime.instructions))
        self.assertTrue(any(event.address == 0x2000 for event in runtime.memory_accesses))
        self.assertIn(("instruction", runtime.instructions[0]), seen)
        self.assertIn(("memory", runtime.memory_accesses[0]), seen)

    def test_reset_restores_registers_and_traces(self):
        runtime = UnicornRuntime()
        runtime.load_synthetic_code(synthetic_sum_program())
        runtime.run()
        self.assertTrue(runtime.instructions)
        runtime.reset()
        self.assertEqual(runtime.registers()["eip"], 0x1000)
        self.assertEqual(runtime.registers()["eax"], 0)
        self.assertEqual(runtime.instructions, [])
        self.assertEqual(runtime.read_memory(0x2000, 4), b"\0\0\0\0")


class OptionalDependencyTests(unittest.TestCase):
    def test_missing_dependency_has_clear_error(self):
        if UNICORN_AVAILABLE:
            self.skipTest("Unicorn is installed; unavailable-path test is not applicable")
        with self.assertRaisesRegex(UnicornUnavailableError, "unicorn.*Python package"):
            UnicornRuntime()


if __name__ == "__main__":
    unittest.main()
