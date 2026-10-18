"""Record one deterministic OpenME fake-model scenario as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from csme.fake_devices.fake_me import FakeME, Request  # noqa: E402


def build_trace() -> dict:
    model = FakeME()
    requests = (
        Request("RESET"),
        Request("START"),
        Request("ENUMERATE"),
        Request("CONNECT", client="openme.echo"),
        Request("DATA", client="openme.echo", payload=b"hello-openme"),
        Request("DISCONNECT", client="openme.echo"),
        Request("SUSPEND"),
        Request("RESUME"),
    )
    for request in requests:
        model.handle(request)
    return {"format": "openme-fake-trace-v0", "trace": model.trace}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write JSON to this path")
    args = parser.parse_args(argv)
    document = build_trace()
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
