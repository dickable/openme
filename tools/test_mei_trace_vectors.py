import copy
import json
import tempfile
import unittest
from pathlib import Path

from mei_trace_vectors import (
    FORMAT,
    SCHEMA,
    VectorValidationError,
    generate_vectors,
    main,
    validate_document,
)


class MeiTraceVectorTests(unittest.TestCase):
    def test_canonical_document_has_required_scenarios(self):
        document = generate_vectors()
        self.assertEqual(document["format"], FORMAT)
        self.assertEqual(document["schema"], SCHEMA)
        validate_document(document)
        self.assertEqual(
            [vector["id"] for vector in document["vectors"]],
            ["reset", "ready", "host-to-me", "me-to-host", "interrupt", "queue-full", "suspend-resume"],
        )

    def test_generation_is_deterministic_and_json_round_trips(self):
        first = json.dumps(generate_vectors(), sort_keys=True, indent=2)
        second = json.dumps(generate_vectors(), sort_keys=True, indent=2)
        self.assertEqual(first, second)
        validate_document(json.loads(first))

    def test_suspend_resume_is_ordered(self):
        vector = generate_vectors()["vectors"][-1]
        self.assertEqual([event["kind"] for event in vector["events"]], ["suspend", "resume"])
        self.assertEqual([event["state"] for event in vector["events"]], ["suspended", "ready"])

    def test_invalid_payload_is_rejected(self):
        document = copy.deepcopy(generate_vectors())
        document["vectors"][2]["events"][0]["details"]["payload_hex"] = "abc"
        with self.assertRaises(VectorValidationError):
            validate_document(document)

    def test_queue_depth_must_equal_capacity(self):
        document = copy.deepcopy(generate_vectors())
        document["vectors"][5]["events"][0]["details"]["depth"] = 7
        with self.assertRaises(VectorValidationError):
            validate_document(document)

    def test_cli_generate_and_validate(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as directory:
            path = Path(directory) / "vectors.json"
            self.assertEqual(main(["generate", "--output", str(path)]), 0)
            self.assertEqual(main(["validate", str(path)]), 0)


if __name__ == "__main__":
    unittest.main()
