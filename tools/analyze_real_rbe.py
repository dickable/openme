"""Emit a bounded analysis report for the real decoded ME11 rbe module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csme.runtime.real_rbe_analysis import analyze_real_rbe, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--dictionary", type=Path, default=Path("qemu-work/third-party/MEAnalyzer/Huffman.dat"))
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--caller-address", type=lambda value: int(value, 0), default=0x40216)
    parser.add_argument("--caller-window", type=lambda value: int(value, 0), default=0x20)
    parser.add_argument("--reference-window", type=lambda value: int(value, 0), default=0x20)
    args = parser.parse_args(argv)
    try:
        report = analyze_real_rbe(
            args.image,
            dictionary_path=args.dictionary,
            trace_path=args.trace,
            caller_address=args.caller_address,
            caller_window=args.caller_window,
            reference_window=args.reference_window,
        )
    except (OSError, KeyError, ValueError, StopIteration) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    serialized = write_report(report, args.output)
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
