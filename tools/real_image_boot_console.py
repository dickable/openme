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
from csme.runtime.real_rbe_analysis import _decode_builtin


def _line(label: str, message: str) -> None:
    print(f"[{label:<12}] {message}", flush=True)


def _instruction_text(event: dict[str, object]) -> str:
    raw = str(event.get("bytes", ""))
    try:
        decoded = _decode_builtin(bytes.fromhex(raw), 0, int(str(event["address"]), 16))
        return str(decoded.get("text", raw))
    except (KeyError, ValueError, TypeError):
        return raw or "<unknown>"


def _live_event(event: dict[str, object]) -> None:
    event_type = event.get("type")
    if event_type == "preflight_complete":
        print("[OpenME] Parsed Intel ME 11 firmware layout", flush=True)
        print(f"[OpenME] Found {event.get('module_count', '?')} modules", flush=True)
    elif event_type == "module_decompressed":
        print("[OpenME] Decompressing RBE module ........ OK", flush=True)
    elif event_type == "runtime_start":
        print("[OpenME] Mapping module memory ........... OK", flush=True)
        print("[OpenME] Initializing x86-32 CPU state ... OK", flush=True)
        print(flush=True)
    elif event_type == "instruction":
        address = int(str(event.get("address", "0")), 16)
        print(f"[EXEC] 0x{address:08X}  {_instruction_text(event)}", flush=True)
    elif event_type in {"mmio", "spi", "memory"}:
        access = str(event.get("access", "access")).upper()
        width = int(event.get("size", 0)) * 8
        address = int(str(event.get("address", "0")), 16)
        value = int(event.get("value", 0))
        label = "MMIO" if event_type == "mmio" else "SPI" if event_type == "spi" else "MEM"
        suffix = f" = 0x{value:0{max(2, int(event.get('size', 1)) * 2)}X}" if access == "WRITE" else ""
        print(f"[{label}] {access}{width} 0x{address:08X}{suffix}", flush=True)
    elif event_type == "external-service":
        if event.get("service") == "rom_memset":
            destination = int(str(event.get("destination", "0")), 16)
            count = int(event.get("count", 0))
            print(f"[ROM ] memset 0x{destination:08X}, 0, 0x{count:X}", flush=True)
    elif event_type == "invalid-memory":
        access = str(event.get("access", "unknown")).upper()
        width = int(event.get("size", 0)) * 8
        address = int(str(event.get("address", "0")), 16)
        value = int(event.get("value", 0))
        value_text = f" = 0x{value:0{max(2, int(event.get('size', 1)) * 2)}X}" if access == "WRITE" else ""
        print(f"[FAULT] {access}{width} 0x{address:08X}{value_text}", flush=True)


def _stop_display(reason: object) -> str:
    text = str(reason)
    lowered = text.lower()
    if "invalid memory fetch" in lowered or "invalid fetch" in lowered:
        return "Unmapped fetch - execution halted"
    if "invalid memory write" in lowered or "invalid write" in lowered:
        return "Unmapped write - execution halted"
    if "invalid memory read" in lowered or "invalid read" in lowered:
        return "Unmapped read - execution halted"
    return text


def run_console(
    image: Path,
    trace: Path,
    delay_ms: int = 120,
    allow_emulation_auth_bypass: bool = False,
    huffman_dictionary: Path | None = None,
    rom_library: Path | None = None,
) -> int:
    delay = max(0, delay_ms) / 1000
    print("REAL FIRMWARE INSTRUCTION EXECUTION", flush=True)
    print("[OpenME] Loading preserved firmware image...", flush=True)
    print(f"[OpenME] Trace: {trace}", flush=True)
    if delay:
        time.sleep(delay)

    report = RealMEImageAttempt(
        image,
        trace,
        allow_emulation_auth_bypass=allow_emulation_auth_bypass,
        huffman_dictionary_path=huffman_dictionary,
        rom_library_path=rom_library,
        event_callback=_live_event,
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
    _line("rom-svc", str(execution.get("external_services", 0)))
    _line("trace", str(execution.get("trace_path", trace)))
    _line("stop", str(execution.get("stop_reason", "unknown")))
    print(f"[STOP] {_stop_display(execution.get('stop_reason', 'unknown'))}", flush=True)
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
    parser.add_argument(
        "--rom-library",
        type=Path,
        default=None,
        help="optional target-generation ROM dump mapped at meloader base 0x1000",
    )
    args = parser.parse_args(argv)
    code = run_console(
        args.image,
        args.trace,
        args.delay_ms,
        args.allow_emulation_auth_bypass,
        args.huffman_dictionary,
        args.rom_library,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
