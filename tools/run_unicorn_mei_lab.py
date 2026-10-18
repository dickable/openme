"""Run one deterministic, synthetic Unicorn-to-MEI lab transaction.

The lab accepts only an opcode and a hexadecimal payload from the command
line.  It does not load firmware, inspect repository data, access hardware,
or use a network connection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csme.mei.unicorn_mei_bridge import (  # noqa: E402
    BridgeError,
    UnicornMEIBridge,
)
from csme.mei.mei_hbm import MessageTooLargeError  # noqa: E402
from csme.cpu.unicorn_runtime import UnicornUnavailableError  # noqa: E402


FORMAT = "openme-unicorn-mei-lab-v1"
MAX_UINT32 = 0xFFFFFFFF


def _parse_uint32(value: str) -> int:
    """Parse a decimal or ``0x``-prefixed non-negative 32-bit integer."""

    try:
        number = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid integer {value!r}; use decimal or 0x-prefixed notation"
        ) from exc
    if not 0 <= number <= MAX_UINT32:
        raise argparse.ArgumentTypeError("opcode must be between 0 and 0xffffffff")
    return number


def _parse_payload_hex(value: str) -> bytes:
    """Parse a synthetic payload supplied as hexadecimal command-line text."""

    try:
        payload = bytes.fromhex(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "payload must be an even-length hexadecimal string"
        ) from exc
    return payload


def _completion_document(result: Any) -> dict[str, Any]:
    completion = result.completion
    return {
        "sequence": completion.sequence,
        "opcode": completion.opcode,
        "status": completion.status,
        "payload_hex": completion.payload.hex(),
        "payload_length": len(completion.payload),
    }


def run_lab(opcode: int, payload: bytes = b"") -> dict[str, Any]:
    """Run one synthetic transaction and return JSON-compatible data."""

    if not isinstance(opcode, int) or not 0 <= opcode <= MAX_UINT32:
        raise BridgeError("opcode must be between 0 and 0xffffffff")
    payload = bytes(payload)

    bridge = UnicornMEIBridge()
    result = bridge.submit(opcode, payload)
    return {
        "format": FORMAT,
        "input": {
            "opcode": opcode,
            "payload_hex": payload.hex(),
            "payload_length": len(payload),
        },
        "completion": _completion_document(result),
        "response_hex": bridge.response_bytes().hex(),
        "events": list(result.events),
        "cpu": {
            "instructions": [
                {"address": event.address, "size": event.size}
                for event in bridge.runtime.instructions
            ],
            "memory_accesses": [
                {
                    "access": event.access,
                    "address": event.address,
                    "size": event.size,
                    "value": event.value,
                }
                for event in bridge.runtime.memory_accesses
            ],
            "registers": bridge.runtime.registers(),
        },
        "transport": {
            "interrupts": int(bridge.model.interrupts),
            "host_to_me_count": bridge.model.host_to_me_count,
            "me_to_host_count": bridge.model.me_to_host_count,
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one synthetic opcode/payload through the Unicorn-to-MEI "
            "bridge and print deterministic JSON."
        )
    )
    parser.add_argument(
        "--opcode",
        type=_parse_uint32,
        default=0x20,
        help="synthetic opcode as decimal or 0x-prefixed integer (default: 0x20)",
    )
    parser.add_argument(
        "--payload-hex",
        type=_parse_payload_hex,
        default=b"hello",
        metavar="HEX",
        help="synthetic payload as hexadecimal text (default: 68656c6c6f)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse synthetic inputs, run the lab, and write one JSON document."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        document = run_lab(args.opcode, args.payload_hex)
    except (
        BridgeError,
        MessageTooLargeError,
        ValueError,
        UnicornUnavailableError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(document, indent=2, sort_keys=True, separators=(",", ": ")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
