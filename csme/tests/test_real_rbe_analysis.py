import json
import unittest

from csme.runtime.real_image_attempt import _evidence_global_layout
from csme.runtime.real_rbe_analysis import analyze_real_rbe, write_report


class RealRBEAnalysisTests(unittest.TestCase):
    def test_report_preserves_fault_path_and_valid_extent(self):
        # This is a bounded analysis fixture, not an execution fixture.  It
        # models the exact decoded bytes used by the observed rbe fault path.
        module = bytearray(0x4000)
        module[0:0x24] = bytes.fromhex(
            "55b80000040689e5ba003004003d04000406730e83c20483c0048b4afc8948fc"
            "ebeb5dc3"
        )
        module[0x210:0x21b] = bytes.fromhex("8b750c8b5d08e8e5fdffff")
        module[0x3000:0x3004] = (0x06041288).to_bytes(4, "little")
        base = 0x40000
        from csme.runtime.real_rbe_analysis import _caller_data_flow, _reference_records

        ranges = [{"name": "valid-code", "start": base, "end": base + 0x29C6}, {"name": "decoded-capacity", "start": base, "end": base + len(module)}]
        caller = _caller_data_flow(bytes(module), base, 0x40216, {"code_base": "0x40000", "code_size": "0x29c6"})
        self.assertEqual(caller["control_flow"][0]["to"], "0x40000")
        self.assertTrue(any(item["text"].startswith("call") for item in caller["disassembly"]["instructions"]))
        self.assertEqual(caller["data_flow"][-1]["destination_address"], "0x6040000")
        self.assertEqual(caller["data_flow"][-1]["value"], "0x6041288")
        target_refs = _reference_records(bytes(module), base, 0x06040000, 0x20, ranges)
        self.assertEqual(target_refs[0]["offset"], "0x2")
        self.assertTrue(target_refs[0]["surrounding_disassembly"]["instructions"])
        refs = _reference_records(bytes(module), base, 0x06041288, 0x20, ranges)
        self.assertEqual(refs[0]["offset"], "0x3000")
        self.assertEqual(refs[0]["address"], "0x43000")
        self.assertIn(
            "0x6041288",
            {item["value"] for item in refs[0]["nearby_pointer_like_values"]},
        )

    def test_report_serialization_is_stable_for_nested_output(self):
        report = {"analysis_domain": "REAL FIRMWARE BYTE ANALYSIS", "references": {"targets": {"0x6040000": []}}}
        text = write_report(report)
        self.assertEqual(json.loads(text), report)
        self.assertEqual(text, write_report(report))

    def test_global_window_requires_pointer_end_and_metadata_bss_correlation(self):
        module = bytearray(0x4000)
        module[0:0x24] = bytes.fromhex(
            "55b80000040689e5ba003004003d04000406730e83c20483c0048b4afc8948fc"
            "ebeb5dc3"
        )
        module[0x3000:0x3004] = (0x06041288).to_bytes(4, "little")
        module[0x2000:0x2004] = (0x06047004).to_bytes(4, "little")
        entry = {
            "module": "rbe",
            "code_base": 0x40000,
            "code_size": 0x29C6,
            "runtime_layout": {"bss_size": 0x7004},
        }
        layout = _evidence_global_layout(bytes(module), entry)
        self.assertEqual(layout["base"], 0x06040000)
        self.assertEqual(layout["end"], 0x06047004)
        module[0x2000:0x2004] = b"\0\0\0\0"
        self.assertIsNone(_evidence_global_layout(bytes(module), entry))

    def test_global_window_derives_variant_pointer_source(self):
        module = bytearray(0x5000)
        module[0:0x24] = bytes.fromhex(
            "55b80000040689e5ba004004003d04000406730e83c20483c0048b4afc8948fc"
            "ebeb5dc3"
        )
        module[0x4000:0x4004] = (0x06041280).to_bytes(4, "little")
        module[0x2400:0x2404] = (0x06047004).to_bytes(4, "little")
        entry = {
            "module": "rbe",
            "code_base": 0x40000,
            "code_size": 0x2F01,
            "runtime_layout": {"bss_size": 0x7004},
        }

        layout = _evidence_global_layout(bytes(module), entry)

        self.assertEqual(layout["base"], 0x06040000)
        self.assertEqual(layout["pointer"], 0x06041280)
        self.assertEqual(layout["source_address"], 0x44000)


if __name__ == "__main__":
    unittest.main()
