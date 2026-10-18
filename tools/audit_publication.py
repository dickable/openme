"""Read-only pre-publication audit for likely firmware artifacts.

This tool checks names and file sizes only. It never opens candidate files,
uploads anything, changes Git metadata, or modifies the scanned directory.
Use it before publishing a repository so vendor firmware is not committed by
accident.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKIP_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", ".venv", "node_modules"}
SUSPICIOUS_DIRECTORY_NAMES = {"downloaded-firmware", "firmware-dumps", "vendor-firmware"}
SUSPICIOUS_SUFFIXES = {".bin", ".rom", ".fd", ".cap", ".efi", ".img", ".iso"}
LARGE_FILE_BYTES = 1024 * 1024


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def audit_tree(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"scan root is not a directory: {root}")

    findings = []
    for directory, child_directories, files in root.walk():
        child_directories[:] = sorted(
            name for name in child_directories if name not in SKIP_DIRECTORIES
        )
        relative_directory = _relative(directory, root)
        if relative_directory == ".":
            relative_directory = ""
        if directory.name.lower() in SUSPICIOUS_DIRECTORY_NAMES:
            findings.append({
                "kind": "suspicious-directory",
                "path": _relative(directory, root),
                "reason": "directory name suggests vendor firmware or dumps",
            })

        for filename in sorted(files):
            path = directory / filename
            try:
                size = path.stat().st_size
            except OSError as exc:
                findings.append({
                    "kind": "unreadable-metadata",
                    "path": _relative(path, root),
                    "reason": str(exc),
                })
                continue
            suffix = path.suffix.lower()
            if suffix in SUSPICIOUS_SUFFIXES:
                findings.append({
                    "kind": "suspicious-file",
                    "path": _relative(path, root),
                    "size": size,
                    "reason": f"file suffix {suffix} may contain firmware or a vendor package",
                })
            elif size >= LARGE_FILE_BYTES:
                findings.append({
                    "kind": "large-file",
                    "path": _relative(path, root),
                    "size": size,
                    "reason": "large files require an explicit publication decision",
                })

    return {
        "root": str(root),
        "read_only": True,
        "files_opened": False,
        "findings": findings,
        "safe_to_publish": not findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="directory to audit; no files are opened")
    args = parser.parse_args(argv)
    try:
        result = audit_tree(args.root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["safe_to_publish"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
