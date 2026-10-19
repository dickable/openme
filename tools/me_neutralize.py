"""Produce a neutralized (HAP + stripped) SPI image from a verified backup.

This wraps the upstream MIT-licensed me_cleaner (https://github.com/corna/me_cleaner).
It does not forge signatures, patch the boot ROM, or bypass verification: it sets the
HAP/AltMeDisable bit the CSME firmware itself honors and removes the non-essential
modules the bring-up tolerates being absent. The on-die ROM still verifies whatever
remains. The output is meant to be reviewed and then written with flash_openme.py.

Workflow:  flash_openme.py backup  ->  me_neutralize.py clean  ->  flash_openme.py write
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

# Intel Flash Descriptor signature (0x0FF0A55A) stored little-endian at offset 0x10.
FD_SIGNATURE = b"\x5a\xa5\xf0\x0f"
FD_SIGNATURE_OFFSET = 0x10


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def resolve_me_cleaner(path: Path) -> Path:
    me = path.resolve()
    if not me.is_file() or me.suffix != ".py":
        raise ValueError(f"--me-cleaner must point to me_cleaner.py (got {path})")
    return me


def load_image(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 0x1000 or len(data) > 128 * 1024 * 1024:
        raise ValueError(f"{path}: not a plausible full SPI image ({len(data)} bytes)")
    if data[FD_SIGNATURE_OFFSET:FD_SIGNATURE_OFFSET + 4] != FD_SIGNATURE:
        # me_cleaner is the authoritative check; this is only a heads-up so the user
        # notices if they fed a partial/ME-region-only dump instead of the full chip.
        print(f"warning: no flash descriptor signature at 0x{FD_SIGNATURE_OFFSET:x}; "
              "this may not be a full-chip image", file=sys.stderr)
    return data


def run_me_cleaner(me_cleaner: Path, args: list[str], log: Path) -> subprocess.CompletedProcess:
    # -I isolates the interpreter so a stray module next to the image can't be imported.
    argv = [sys.executable, "-I", str(me_cleaner), *args]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    log.write_text(
        f"$ {' '.join(argv)}\n\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
        encoding="utf-8",
    )
    return result


def analyze(image: Path, me_cleaner: Path, output: Path) -> dict:
    me = resolve_me_cleaner(me_cleaner)
    data = load_image(image)
    output.mkdir(parents=True, exist_ok=False)
    result = run_me_cleaner(me, ["-c", str(image.resolve())], output / "check.log")
    if result.returncode:
        raise RuntimeError(f"me_cleaner -c failed ({result.returncode}); see {output / 'check.log'}")
    record = {
        "schema": 1,
        "image": str(image.resolve()),
        "image_sha256": sha256(data),
        "image_size": len(data),
        "me_cleaner_report": result.stdout.strip().splitlines(),
    }
    save(output / "analysis.json", record)
    return record


def count_changed(original: bytes, candidate: bytes) -> dict:
    if len(original) != len(candidate):
        # me_cleaner without --truncate/--relocate keeps the size; a changed size here
        # means options were used that flash_openme.py's same-capacity write won't accept.
        return {"changed_bytes": None, "note": "sizes differ (truncate/relocate used)",
                "original_size": len(original), "candidate_size": len(candidate)}
    changed = sum(1 for a, b in zip(original, candidate) if a != b)
    first = next((i for i in range(len(original)) if original[i] != candidate[i]), None)
    last = next((i for i in range(len(original) - 1, -1, -1) if original[i] != candidate[i]), None)
    return {"changed_bytes": changed,
            "first_changed_offset": first, "last_changed_offset": last}


def clean(image: Path, me_cleaner: Path, output: Path, *, hap_only: bool) -> dict:
    me = resolve_me_cleaner(me_cleaner)
    original = load_image(image)
    output.mkdir(parents=True, exist_ok=False)
    cleaned = output / "neutralized.bin"
    # -S : set the HAP/AltMeDisable bit only (leave modules in place)
    # -s : remove non-essential modules AND set the disable bit (fuller neutralization)
    # -O : write to a new file; the input image is never modified in place
    mode = "-S" if hap_only else "-s"
    result = run_me_cleaner(me, [mode, "-O", str(cleaned), str(image.resolve())], output / "clean.log")
    if result.returncode or not cleaned.is_file():
        raise RuntimeError(f"me_cleaner {mode} failed ({result.returncode}); see {output / 'clean.log'}")

    candidate = cleaned.read_bytes()
    # Re-check the produced image so we never hand a write step something that no
    # longer parses as a valid ME layout.
    recheck = run_me_cleaner(me, ["-c", str(cleaned)], output / "recheck.log")
    if recheck.returncode:
        raise RuntimeError(f"neutralized image failed re-check; see {output / 'recheck.log'}")

    record = {
        "schema": 1,
        "mode": "hap-only" if hap_only else "strip+hap",
        "source_image": str(image.resolve()),
        "source_sha256": sha256(original),
        "neutralized_image": str(cleaned.resolve()),
        "neutralized_sha256": sha256(candidate),
        "diff": count_changed(original, candidate),
        "next_step": ("Review clean.log, then write with flash_openme.py using this image "
                      "and --confirm-sha256 " + sha256(candidate)),
    }
    save(output / "neutralize.json", record)
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    a = commands.add_parser("analyze", help="report the ME layout of a backup image (read-only)")
    a.add_argument("--image", type=Path, required=True, help="a verified full-chip backup")
    a.add_argument("--me-cleaner", type=Path, required=True, help="path to upstream me_cleaner.py")
    a.add_argument("--output", type=Path, required=True)

    c = commands.add_parser("clean", help="produce a neutralized image (does not touch hardware)")
    c.add_argument("--image", type=Path, required=True, help="a verified full-chip backup")
    c.add_argument("--me-cleaner", type=Path, required=True, help="path to upstream me_cleaner.py")
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--hap-only", action="store_true",
                   help="set the disable bit only, leave modules (default: strip modules too)")

    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            result = analyze(args.image, args.me_cleaner, args.output.resolve())
        else:
            result = clean(args.image, args.me_cleaner, args.output.resolve(), hap_only=args.hap_only)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Neutralization stopped: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
