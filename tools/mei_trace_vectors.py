"""Generate and validate deterministic, project-defined MEI trace vectors.

These vectors describe OpenME test scenarios only.  They are not Intel wire
traces, hardware captures, or firmware-derived data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


FORMAT = "openme-mei-trace-vectors-v0"
SCHEMA = "openme-project-defined-mei-vector-v0"
EVENT_KINDS = {
    "reset",
    "ready",
    "host-to-me",
    "me-to-host",
    "interrupt",
    "queue-full",
    "suspend",
    "resume",
}
VECTOR_IDS = (
    "reset",
    "ready",
    "host-to-me",
    "me-to-host",
    "interrupt",
    "queue-full",
    "suspend-resume",
)
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HEX = re.compile(r"^(?:[0-9a-f]{2})*$")


class VectorValidationError(ValueError):
    """Raised when a vector document violates the project-defined schema."""


def _event(seq: int, kind: str, actor: str, state: str, **details: Any) -> dict[str, Any]:
    return {
        "seq": seq,
        "kind": kind,
        "actor": actor,
        "state": state,
        "details": details,
    }


def generate_vectors() -> dict[str, Any]:
    """Return the canonical deterministic vector document."""

    return {
        "format": FORMAT,
        "schema": SCHEMA,
        "description": (
            "Project-defined deterministic scenarios for the OpenME host-facing "
            "model; not Intel wire traces."
        ),
        "vectors": [
            {
                "id": "reset",
                "description": "Host requests a clean model reset.",
                "events": [_event(0, "reset", "host", "reset", reason="host-reset")],
            },
            {
                "id": "ready",
                "description": "The model reports that it is ready for host traffic.",
                "events": [_event(0, "ready", "me", "ready", firmware_status="ready")],
            },
            {
                "id": "host-to-me",
                "description": "A host message enters the model's bounded test channel.",
                "events": [
                    _event(
                        0,
                        "host-to-me",
                        "host",
                        "ready",
                        channel="openme.control",
                        message="PING",
                        payload_hex="6f70656e6d65",
                    )
                ],
            },
            {
                "id": "me-to-host",
                "description": "The model returns a deterministic response to the host.",
                "events": [
                    _event(
                        0,
                        "me-to-host",
                        "me",
                        "ready",
                        channel="openme.control",
                        message="PONG",
                        payload_hex="6f70656e6d65",
                    )
                ],
            },
            {
                "id": "interrupt",
                "description": "The model signals that a response is available.",
                "events": [
                    _event(
                        0,
                        "interrupt",
                        "me",
                        "ready",
                        vector=0,
                        reason="response-ready",
                    )
                ],
            },
            {
                "id": "queue-full",
                "description": "A bounded queue rejects traffic after reaching capacity.",
                "events": [
                    _event(
                        0,
                        "queue-full",
                        "host",
                        "ready",
                        queue="host-to-me",
                        capacity=8,
                        depth=8,
                        rejected="PING",
                    )
                ],
            },
            {
                "id": "suspend-resume",
                "description": "The model enters suspend and then returns to ready.",
                "events": [
                    _event(0, "suspend", "host", "suspended", transition="suspend"),
                    _event(1, "resume", "host", "ready", transition="resume"),
                ],
            },
        ],
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VectorValidationError(message)


def _validate_event(event: Any, vector_id: str, expected_seq: int) -> None:
    prefix = f"vector {vector_id!r} event {expected_seq}"
    _require(isinstance(event, dict), f"{prefix}: event must be an object")
    _require(set(event) == {"seq", "kind", "actor", "state", "details"}, f"{prefix}: invalid event keys")
    _require(event["seq"] == expected_seq, f"{prefix}: seq must be {expected_seq}")
    _require(event["kind"] in EVENT_KINDS, f"{prefix}: unsupported event kind")
    _require(event["actor"] in {"host", "me"}, f"{prefix}: actor must be host or me")
    _require(isinstance(event["state"], str) and event["state"], f"{prefix}: state must be non-empty")
    details = event["details"]
    _require(isinstance(details, dict), f"{prefix}: details must be an object")

    kind = event["kind"]
    required = {
        "reset": {"reason"},
        "ready": {"firmware_status"},
        "host-to-me": {"channel", "message", "payload_hex"},
        "me-to-host": {"channel", "message", "payload_hex"},
        "interrupt": {"vector", "reason"},
        "queue-full": {"queue", "capacity", "depth", "rejected"},
        "suspend": {"transition"},
        "resume": {"transition"},
    }[kind]
    _require(required <= set(details), f"{prefix}: missing details for {kind}")

    if kind in {"host-to-me", "me-to-host"}:
        _require(details["channel"] == "openme.control", f"{prefix}: unsupported project channel")
        _require(isinstance(details["message"], str) and details["message"], f"{prefix}: message must be non-empty")
        _require(isinstance(details["payload_hex"], str), f"{prefix}: payload_hex must be a string")
        _require(bool(_HEX.fullmatch(details["payload_hex"])), f"{prefix}: payload_hex must be even lowercase hex")
    elif kind == "interrupt":
        _require(isinstance(details["vector"], int) and details["vector"] >= 0, f"{prefix}: vector must be non-negative")
    elif kind == "queue-full":
        _require(details["queue"] == "host-to-me", f"{prefix}: unsupported project queue")
        _require(isinstance(details["capacity"], int) and details["capacity"] > 0, f"{prefix}: capacity must be positive")
        _require(details["depth"] == details["capacity"], f"{prefix}: full queue depth must equal capacity")
        _require(isinstance(details["rejected"], str) and details["rejected"], f"{prefix}: rejected must be non-empty")
    elif kind == "suspend":
        _require(details["transition"] == "suspend" and event["state"] == "suspended", f"{prefix}: invalid suspend transition")
    elif kind == "resume":
        _require(details["transition"] == "resume" and event["state"] == "ready", f"{prefix}: invalid resume transition")


def validate_document(document: Any) -> dict[str, Any]:
    """Validate and return *document*, raising ``VectorValidationError`` on failure."""

    _require(isinstance(document, dict), "document must be an object")
    _require(set(document) == {"format", "schema", "description", "vectors"}, "invalid document keys")
    _require(document["format"] == FORMAT, "unsupported document format")
    _require(document["schema"] == SCHEMA, "unsupported schema")
    _require(isinstance(document["description"], str) and "not Intel wire traces" in document["description"], "missing non-Intel disclaimer")
    vectors = document["vectors"]
    _require(isinstance(vectors, list), "vectors must be a list")
    _require([vector.get("id") for vector in vectors if isinstance(vector, dict)] == list(VECTOR_IDS), "vectors must contain the canonical IDs in order")

    for vector in vectors:
        _require(isinstance(vector, dict), "vector must be an object")
        _require(set(vector) == {"id", "description", "events"}, f"vector has invalid keys: {vector!r}")
        vector_id = vector["id"]
        _require(isinstance(vector_id, str) and _SLUG.fullmatch(vector_id), "vector id must be a lowercase slug")
        _require(isinstance(vector["description"], str) and vector["description"], f"vector {vector_id!r}: description required")
        events = vector["events"]
        _require(isinstance(events, list) and events, f"vector {vector_id!r}: events must be non-empty")
        for expected_seq, event in enumerate(events):
            _validate_event(event, vector_id, expected_seq)

    _require(vectors[-1]["id"] == "suspend-resume", "suspend-resume vector must be last")
    _require([event["kind"] for event in vectors[-1]["events"]] == ["suspend", "resume"], "suspend-resume must contain suspend then resume")
    return document


def load_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VectorValidationError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VectorValidationError(f"invalid JSON in {path}: {exc}") from exc
    return validate_document(document)


def _write_json(document: dict[str, Any], output: Path | None) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(encoded, end="")
    else:
        output.write_text(encoded, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="generate canonical deterministic vectors")
    generate.add_argument("--output", type=Path, help="write JSON to this path")

    validate = subparsers.add_parser("validate", help="validate a vector JSON document")
    validate.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            document = generate_vectors()
            validate_document(document)
            _write_json(document, args.output)
            return 0
        document = load_document(args.path)
        print(f"VALID: {len(document['vectors'])} vectors")
        return 0
    except (OSError, VectorValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
