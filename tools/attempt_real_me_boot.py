"""Attempt real instruction execution from one preserved SPI image."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csme.runtime.real_image_attempt import RealMEImageAttempt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--trace", type=Path, default=None)
    parser.add_argument(
        "--allow-emulation-auth-bypass",
        action="store_true",
        help="explicitly bypass only the local emulator admission gate; never affects hardware",
    )
    parser.add_argument("--huffman-dictionary", type=Path, default=None)
    parser.add_argument(
        "--rom-library",
        type=Path,
        default=None,
        help="optional target-generation ROM dump mapped at meloader base 0x1000",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            RealMEImageAttempt(
                args.image,
                args.trace,
                allow_emulation_auth_bypass=args.allow_emulation_auth_bypass,
                huffman_dictionary_path=args.huffman_dictionary,
                rom_library_path=args.rom_library,
            ).run(),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
