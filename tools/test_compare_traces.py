import json
import tempfile
import unittest
from pathlib import Path

from compare_traces import compare_traces, load_trace, main, normalize_trace


class CompareTraceTests(unittest.TestCase):
    def test_normalization_accepts_trace_wrapper_and_ignores_capture_fields(self):
        raw = {
            "trace": [{
                "event": 42,
                "direction": "host",
                "message": "DATA",
                "payload": "6869",
                "timestamp_ns": 123,
            }],
        }
        self.assertEqual(normalize_trace(raw), [{
            "direction": "host",
            "message": "DATA",
            "payload": "6869",
        }])

    def test_equivalent_traces_match_despite_event_numbers_and_key_order(self):
        left = normalize_trace([{
            "event": 1,
            "message": "RESET",
            "direction": "device",
        }])
        right = normalize_trace([{
            "direction": "device",
            "event": 99,
            "message": "RESET",
        }])
        self.assertEqual(compare_traces(left, right), [])

    def test_mismatch_identifies_event_and_field(self):
        left = normalize_trace([{"event": 1, "message": "DATA", "payload": "6869"}])
        right = normalize_trace([{"event": 4, "message": "DATA", "payload": "686a"}])
        self.assertEqual(
            compare_traces(left, right),
            ['event[0].payload: left="6869" right="686a"'],
        )

    def test_missing_event_is_reported(self):
        differences = compare_traces(
            normalize_trace([{"message": "RESET"}, {"message": "START"}]),
            normalize_trace([{"message": "RESET"}]),
        )
        self.assertEqual(differences, [
            'event[1]: left={"message":"START"} right=<missing>',
        ])

    def test_cli_returns_match_and_mismatch_statuses(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text(json.dumps([{"event": 1, "message": "RESET"}]), encoding="utf-8")
            second.write_text(json.dumps({"events": [{"event": 2, "message": "RESET"}]}), encoding="utf-8")
            self.assertEqual(main([str(first), str(second)]), 0)

            second.write_text(json.dumps([{"event": 2, "message": "START"}]), encoding="utf-8")
            self.assertEqual(main([str(first), str(second)]), 1)


if __name__ == "__main__":
    unittest.main()
