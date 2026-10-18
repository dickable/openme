import unittest

from csme.runtime.module_loader import build_module_plan


class ModuleLoaderTests(unittest.TestCase):
    def test_bounded_entries_are_classified_by_storage_format(self):
        plan = build_module_plan(
            cpd_entries=[
                {"name": "kernel", "offset_in_partition": 0x200, "size": 0x1000, "flags": 2},
                {"name": "pm", "offset_in_partition": 0x1400, "size": 0x200, "flags": 0},
            ],
            ftpr_absolute_offset=0x4000,
            ftpr_size=0x2000,
            me_absolute_offset=0x3000,
            profile="skylake-t460-research-v0",
        )
        self.assertEqual([m.name for m in plan.modules], ["kernel", "pm"])
        self.assertTrue(all(m.bounds_valid for m in plan.modules))
        self.assertTrue(plan.execution_ready)
        self.assertEqual(plan.modules[0].compression, "huffman")
        self.assertEqual(plan.modules[1].compression, "uncompressed")
        self.assertEqual(plan.errors, ())
        self.assertEqual(plan.warnings, ())

    def test_out_of_bounds_entry_is_rejected(self):
        plan = build_module_plan(
            cpd_entries=[{"name": "bad", "offset_in_partition": 0x1F00, "size": 0x200}],
            ftpr_absolute_offset=0x4000,
            ftpr_size=0x2000,
            me_absolute_offset=0x3000,
            profile="skylake-t460-research-v0",
        )
        self.assertFalse(plan.modules[0].bounds_valid)
        self.assertTrue(plan.errors)
        self.assertFalse(plan.execution_ready)

    def test_me11_metadata_stored_size_bounds_overlapping_cpd_ranges(self):
        plan = build_module_plan(
            cpd_entries=[
                {
                    "name": "rbe",
                    "packed_offset": 0x02003D80,
                    "offset_in_partition": 0x3D80,
                    "size": 0x4000,
                    "flags": 0x02,
                },
            ],
            ftpr_absolute_offset=0x4000,
            ftpr_size=0x12F000,
            me_absolute_offset=0x3000,
            profile="skylake-t460-real-image-v1",
            image_size=0x200000,
            module_sizes={"rbe": {"uncompressed_size": 0x4000, "stored_size": 0x2610}},
        )

        self.assertEqual(plan.modules[0].size, 0x2610)
        self.assertEqual(plan.modules[0].declared_size, 0x4000)
        self.assertEqual(plan.modules[0].compression, "huffman")
        self.assertFalse(plan.modules[0].executable_candidate)


if __name__ == "__main__":
    unittest.main()
