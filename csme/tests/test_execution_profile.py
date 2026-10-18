import unittest

from csme.runtime.execution_profile import SKYLAKE_T460_PROFILE, profile_for_target


class ExecutionProfileTests(unittest.TestCase):
    def test_profile_identifies_real_execution_engine_and_missing_dependencies(self):
        profile = profile_for_target()
        self.assertIs(profile, SKYLAKE_T460_PROFILE)
        self.assertTrue(profile.instruction_execution_enabled)
        self.assertEqual(profile.isa, "x86-32")
        self.assertEqual(profile.word_size_bits, 32)
        self.assertIn("Intel ME reset ROM/library image", profile.unsupported_requirements)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            profile_for_target("universal-skylake")


if __name__ == "__main__":
    unittest.main()
