"""Compare two deterministic OpenME event traces stored as JSON.

The input may be a JSON list of events or an object containing a ``trace`` or
``events`` list.  Event sequence counters and common timing fields are ignored
because they describe capture bookkeeping rather than model behavior.  All
other event fields remain part of the comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


VOLATILE_FIELDS = frozenset({
    "event",
    "timestamp",
    "timestamp_ns",
    "time",
    "elapsed",
    "elapsed_ms",
    "elapsed_ns",
})


def _canonicalize(value: Any) -> Any:
    """Return JSON data with recursively sorted object keys."""

    if isinstance(value, dict):
        return {
            str(key): _canonicalize(value[key])
            for key in sorted(value, key=str)
        }
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def normalize_trace(raw: Any) -> list[dict[str, Any]]:
    """Extract and normalize a trace from decoded JSON data.

    Sequence and timing fields are removed.  Event order is retained, so an
    insertion, omission, or reordering still produces a useful mismatch at a
    specific event index.
    """

    if isinstance(raw, list):
        events = raw
    elif isinstance(raw, dict):
        candidates = [raw[name] for name in ("trace", "events") if name in raw]
        if len(candidates) != 1:
            raise ValueError("trace JSON object must contain exactly one of 'trace' or 'events'")
        events = candidates[0]
    else:
        raise ValueError("trace JSON must be a list or an object containing 'trace' or 'events'")

    if not isinstance(events, list):
        raise ValueError("trace/events value must be a list")

    normalized = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"event {index} must be a JSON object")
        kept = {
            str(key): _canonicalize(value)
            for key, value in event.items()
            if str(key) not in VOLATILE_FIELDS
        }
        normalized.append(_canonicalize(kept))
    return normalized


def load_trace(path: Path) -> list[dict[str, Any]]:
    """Read and normalize one trace file without modifying it."""

    try:
        with path.open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc.msg} at line {exc.lineno}, column {exc.colno}") from exc
    return normalize_trace(raw)


def _json_value(value: Any) -> str:
    if value is _MISSING:
        return "<missing>"
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class _Missing:
    pass


_MISSING = _Missing()


def _diff_values(left: Any, right: Any, path: str) -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        differences = []
        for key in sorted(set(left) | set(right)):
            differences.extend(_diff_values(
                left.get(key, _MISSING), right.get(key, _MISSING),
                f"{path}.{key}",
            ))
        return differences
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        for index in range(max(len(left), len(right))):
            differences.extend(_diff_values(
                left[index] if index < len(left) else _MISSING,
                right[index] if index < len(right) else _MISSING,
                f"{path}[{index}]",
            ))
        return differences
    if left != right:
        return [f"{path}: left={_json_value(left)} right={_json_value(right)}"]
    return []


def compare_traces(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[str]:
    """Return human-readable field-level differences between normalized traces."""

    differences = []
    for index in range(max(len(left), len(right))):
        left_event = left[index] if index < len(left) else _MISSING
        right_event = right[index] if index < len(right) else _MISSING
        differences.extend(_diff_values(left_event, right_event, f"event[{index}]"))
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path, help="first JSON trace")
    parser.add_argument("right", type=Path, help="second JSON trace")
    args = parser.parse_args(argv)

    try:
        left = load_trace(args.left)
        right = load_trace(args.right)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    differences = compare_traces(left, right)
    if not differences:
        print(f"MATCH: {len(left)} normalized events")
        return 0

    print(f"MISMATCH: {len(differences)} difference(s)")
    for difference in differences:
        print(f"- {difference}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
