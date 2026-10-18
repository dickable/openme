import unittest

from csme.runtime.cse_metadata import parse_module_metadata


class CseMetadataTests(unittest.TestCase):
    def test_process_attributes_entry_is_bounded_and_decoded(self):
        blob = bytearray(0x38 + 0x2C)
        blob[0x38:0x40] = (5).to_bytes(4, "little") + (0x2C).to_bytes(4, "little")
        values = (6, 1, 0x40000, 0x300, 0x100, 0x20, 0x80, 0x4020A)
        for index, value in enumerate(values):
            start = 0x40 + index * 4
            blob[start:start + 4] = value.to_bytes(4, "little")

        result = parse_module_metadata(bytes(blob))

        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["extensions"], [{"tag": 5, "offset": 0x38, "size": 0x2C}])
        process = result["process_attributes"][0]
        self.assertEqual(process["code_base"], "0x40000")
        self.assertEqual(process["main_thread_entry"], "0x4020a")
        self.assertEqual(process["entry_offset"], "0x20a")
        self.assertTrue(process["entry_in_code_range"])

    def test_out_of_range_entry_is_not_admitted(self):
        blob = bytearray(0x38 + 0x2C)
        blob[0x38:0x40] = (5).to_bytes(4, "little") + (0x2C).to_bytes(4, "little")
        values = (6, 1, 0x40000, 0x300, 0x100, 0x20, 0x80, 0x50000)
        for index, value in enumerate(values):
            start = 0x40 + index * 4
            blob[start:start + 4] = value.to_bytes(4, "little")

        process = parse_module_metadata(bytes(blob))["process_attributes"][0]

        self.assertIsNone(process["entry_offset"])
        self.assertFalse(process["entry_in_code_range"])

    def test_thread_extension_preserves_stack_metadata(self):
        blob = bytearray(0x38 + 0x2C + 0x14)
        blob[0x38:0x40] = (5).to_bytes(4, "little") + (0x2C).to_bytes(4, "little")
        values = (6, 1, 0x40000, 0x4000, 0, 0x7004, 0x1000, 0x4020A)
        for index, value in enumerate(values):
            start = 0x40 + index * 4
            blob[start:start + 4] = value.to_bytes(4, "little")
        offset = 0x38 + 0x2C
        blob[offset:offset + 8] = (6).to_bytes(4, "little") + (0x14).to_bytes(4, "little")
        blob[offset + 8:offset + 20] = (
            (0x1000).to_bytes(4, "little")
            + (1).to_bytes(4, "little")
            + (0).to_bytes(4, "little")
        )

        result = parse_module_metadata(bytes(blob))

        self.assertEqual(result["thread_info"][0]["stack_size"], 0x1000)
        self.assertEqual(result["thread_info"][0]["flags"], 1)

    def test_shared_library_and_locked_range_metadata_are_decoded(self):
        blob = bytearray(0x38 + 0x1C + 0x10)
        offset = 0x38
        blob[offset:offset + 8] = (4).to_bytes(4, "little") + (0x1C).to_bytes(4, "little")
        blob[offset + 8:offset + 28] = b"".join(value.to_bytes(4, "little") for value in (0x218, 0x24000, 0, 0, 0xFFFFFFFF))
        offset += 0x1C
        blob[offset:offset + 8] = (0x0B).to_bytes(4, "little") + (0x10).to_bytes(4, "little")
        blob[offset + 8:offset + 16] = (0x9000).to_bytes(4, "little") + (0).to_bytes(4, "little")

        result = parse_module_metadata(bytes(blob))

        self.assertEqual(result["shared_library"]["context_size"], 0x218)
        self.assertEqual(result["shared_library"]["total_alloc_virtual_space"], 0x24000)
        self.assertEqual(result["locked_ranges"][0]["base"], 0x9000)


if __name__ == "__main__":
    unittest.main()
