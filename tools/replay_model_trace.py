"""Replay host requests from a fake-model trace and compare the result."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from compare_traces import compare_traces, normalize_trace  # noqa: E402
from csme.fake_devices.fake_me import FakeME, Request  # noqa: E402


def replay(document: dict) -> list[dict]:
    raw_trace = document.get("trace", document) if isinstance(document, dict) else document
    if not isinstance(raw_trace, list):
        raise ValueError("trace document must contain a list under 'trace'")
    model = FakeME()
    for event in raw_trace:
        if event.get("direction") != "host":
            continue
        payload_hex = event.get("payload", "")
        try:
            payload = bytes.fromhex(payload_hex)
        except ValueError as exc:
            raise ValueError("host event payload is not hexadecimal") from exc
        model.handle(Request(
            event["message"],
            client=event.get("client", ""),
            payload=payload,
            version=event.get("version", 1),
        ))
    return model.trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.trace.read_text(encoding="utf-8"))
        expected = normalize_trace(document)
        actual = normalize_trace(replay(document))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    differences = compare_traces(expected, actual)
    if differences:
        print(f"MISMATCH: {len(differences)} difference(s)")
        for difference in differences:
            print(f"- {difference}")
        return 1
    print(f"REPLAY MATCH: {len(actual)} normalized events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
