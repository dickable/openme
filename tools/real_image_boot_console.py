"""Display the real-byte execution attempt in a visible console."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csme.runtime.real_image_attempt import RealMEImageAttempt


def _line(label: str, message: str) -> None:
    print(f"[{label:<12}] {message}", flush=True)


def run_console(
    image: Path,
    trace: Path,
    delay_ms: int = 120,
    allow_emulation_auth_bypass: bool = False,
    huffman_dictionary: Path | None = None,
) -> int:
    delay = max(0, delay_ms) / 1000
    print("REAL FIRMWARE INSTRUCTION EXECUTION", flush=True)
    print(f"image: {image}", flush=True)
    print(f"trace: {trace}", flush=True)

    stages = [
        ("preserve", "verifying the preserved working copy and SHA-256"),
        ("format", "identifying descriptor, ME region, FPT, FTPR, and CPD"),
        ("cpu", "checking the image-specific x86-32 execution profile"),
        ("loader", "classifying bounded module ranges and compression state"),
        ("entry", "resolving reset-vector and module entry metadata"),
        ("execute", "starting real bytes only if all gates are satisfied"),
    ]
    for label, message in stages:
        _line(label, message)
        if delay:
            time.sleep(delay)

    report = RealMEImageAttempt(
        image,
        trace,
        allow_emulation_auth_bypass=allow_emulation_auth_bypass,
        huffman_dictionary_path=huffman_dictionary,
    ).run()
    execution = report.get("execution", {})
    architecture = report.get("architecture", {})
    entry = report.get("entry_metadata") or {}
    modules = report.get("module_plan") or {}
    print("-" * 78, flush=True)
    _line("sha256", report.get("image", {}).get("sha256", "unknown"))
    _line("isa", architecture.get("isa", "unknown"))
    _line("format", architecture.get("module_format", "unknown"))
    _line("compress", json.dumps(architecture.get("compression_flags", {}), sort_keys=True))
    _line("modules", str(len(modules.get("modules", []))))
    _line("entry", f"{entry.get('entry_point_status', 'unknown')}: {entry.get('entry_point_reason', '')}")
    _line("auth", str((report.get("authentication") or {}).get("status", "unknown")))
    _line("decomp", str((report.get("decompression") or {}).get("status", "unknown")))
    _line("result", report.get("status", "unknown"))
    _line("instructions", str(execution.get("instructions_executed", 0)))
    _line("bytes", str(execution.get("bytes_executed", 0)))
    _line("mmio", str(execution.get("mmio_accesses", 0)))
    _line("trace", str(execution.get("trace_path", trace)))
    _line("stop", str(execution.get("stop_reason", "unknown")))
    print("-" * 78, flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        nargs="?",
        type=Path,
        default=ROOT / "working-copies" / "Lenovo T460 NM-A581.bin",
    )
    parser.add_argument(
        "--trace",
        type=Path,
        default=ROOT / "qemu-work" / "traces" / "real-me-execution.jsonl",
    )
    parser.add_argument("--delay-ms", type=int, default=120)
    parser.add_argument(
        "--allow-emulation-auth-bypass",
        action="store_true",
        help="explicitly bypass only the local emulator admission gate",
    )
    parser.add_argument("--huffman-dictionary", type=Path, default=None)
    args = parser.parse_args(argv)
    code = run_console(
        args.image,
        args.trace,
        args.delay_ms,
        args.allow_emulation_auth_bypass,
        args.huffman_dictionary,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
