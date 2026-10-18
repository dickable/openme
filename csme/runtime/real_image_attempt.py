"""Attempt execution of actual bytes from a preserved Intel ME image.

This is a real-byte path, not a synthetic boot. It performs strict image
identification and bounded loading, then hands a selected uncompressed module
to Unicorn only when a verified entry point and required runtime state exist.
The current T460 dump reaches a controlled stop because the ME ROM/library and
documented entry selector are not present in the SPI dump.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from parsers.inspect_cpd import inspect_cpd
    from parsers.inspect_cpd_manifest import inspect_cpd_manifest
    from parsers.inspect_ifd import inspect_ifd
    from parsers.inspect_me import inspect_me
except ImportError:  # pragma: no cover
    inspect_cpd = None
    inspect_cpd_manifest = None
    inspect_ifd = None
    inspect_me = None

from .execution_profile import SKYLAKE_T460_PROFILE
from .cse_metadata import parse_module_metadata
from .huffman import HuffmanDecodeError, decompress_me11_huffman, load_me11_dictionary
from .module_loader import (
    build_module_plan,
    load_bounded_module,
    load_verified_module_bytes,
)
from .real_firmware_runtime import RealRuntimeConfig, RealUnicornRuntime, UNICORN_AVAILABLE


class AttemptStatus(str, Enum):
    PRECHECK_FAILED = "precheck-failed"
    STOPPED_BEFORE_EXECUTION = "stopped-before-instruction-execution"
    EXECUTION_STOPPED = "real-execution-stopped"
    EXECUTION_COMPLETED = "real-execution-completed"
    # Kept as a compatibility value for old reports and callers.
    REJECTED_BEFORE_EXECUTION = "rejected-before-instruction-execution"


@dataclass(frozen=True)
class ReadOnlyMapping:
    name: str
    image_offset: int
    size: int
    guest_base: int
    permissions: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "image_offset": f"0x{self.image_offset:x}",
            "size": f"0x{self.size:x}",
            "guest_base": f"0x{self.guest_base:x}",
            "permissions": self.permissions,
        }


def _metadata_summary(image: bytes, ftpr_offset: int, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Record bounded ME11 metadata and verified process-entry fields."""

    summaries: list[dict[str, Any]] = []
    by_name = {str(item.get("name")): item for item in entries}
    for item in entries:
        name = str(item.get("name") or "")
        if not name.endswith(".met"):
            continue
        start = ftpr_offset + int(item.get("offset_in_partition", -1))
        size = int(item.get("size", 0))
        end = start + size
        if start < 0 or size <= 0 or end > len(image) or size < 0x38:
            continue
        blob = image[start:end]
        metadata = parse_module_metadata(blob)
        tags = metadata["extensions"]
        module_name = name[:-4]
        module = by_name.get(module_name)
        process_attributes = metadata["process_attributes"]
        process_entry = next(
            (item for item in process_attributes if item.get("entry_in_code_range")),
            None,
        )
        runtime_layout = (
            _module_runtime_layout(process_entry, metadata)
            if process_entry is not None
            else None
        )
        summaries.append(
            {
                "metadata_name": name,
                "module_name": module_name,
                "module_present": module is not None,
                "extension_tags": tags,
                "process_attributes": process_attributes,
                "thread_info": metadata["thread_info"],
                "shared_library": metadata["shared_library"],
                "locked_ranges": metadata["locked_ranges"],
                "module_size_fields": metadata["module_size_fields"],
                "entry_point": (
                    {
                        "module": module_name,
                        "address": int(process_entry["main_thread_entry"], 16),
                        "offset": int(process_entry["entry_offset"], 16),
                        "code_base": int(process_entry["code_base"], 16),
                        "code_size": int(process_entry["code_size"], 16),
                        "runtime_layout": runtime_layout,
                        "source": "bounded CSE process-attributes extension 0x05",
                    }
                    if process_entry is not None
                    else None
                ),
                "entry_point_reason": (
                    "bounded CSE process-attributes extension 0x05"
                    if process_entry is not None
                    else "no in-range process entry was present"
                ),
                "metadata_warnings": metadata["warnings"],
            }
        )
    return {
        "metadata_entries": summaries,
        "module_sizes": {
            item["module_name"]: item["module_size_fields"]
            for item in summaries
            if item.get("module_size_fields")
        },
        "entry_point": next(
            (item["entry_point"] for item in summaries if item.get("entry_point")),
            None,
        ),
        "entry_point_status": (
            "module-entry-metadata-found"
            if any(item.get("entry_point") for item in summaries)
            else "unresolved"
        ),
        "entry_point_reason": (
            "The preserved SPI image contains bounded module entry metadata, but "
            "the ME reset ROM/library still supplies the boot selector and initial state."
            if any(item.get("entry_point") for item in summaries)
            else "No bounded process entry metadata was found."
        ),
    }


def _module_runtime_layout(entry: dict[str, Any], metadata: dict[str, Any]) -> dict[str, int] | None:
    """Derive only the text/rodata/stack/heap/BSS layout evidenced by metadata."""

    process = next(
        (
            item
            for item in metadata.get("process_attributes", [])
            if item.get("entry_in_code_range")
        ),
        None,
    )
    size_fields = metadata.get("module_size_fields") or {}
    threads = metadata.get("thread_info") or []
    if process is None or not threads:
        return None
    code_base = int(process["code_base"], 16)
    code_size = int(process["code_size"], 16)
    module_capacity = int(size_fields.get("uncompressed_size", 0))
    if module_capacity < code_size:
        return None
    thread_stack_size = int(threads[0].get("stack_size", 0))
    default_heap_size = int(process["default_heap_size"], 16)
    bss_size = int(process["bss_size"], 16)
    module_end = code_base + module_capacity
    guard_base = module_end
    stack_base = guard_base + 0x1000
    stack_top = stack_base + thread_stack_size
    heap_base = stack_top
    bss_base = heap_base + default_heap_size
    return {
        "code_base": code_base,
        "code_size": code_size,
        "module_capacity": module_capacity,
        "rodata_base": code_base + code_size,
        "rodata_size": module_capacity - code_size,
        "guard_base": guard_base,
        "stack_base": stack_base,
        "stack_size": thread_stack_size,
        "stack_top": stack_top,
        "heap_base": heap_base,
        "heap_size": default_heap_size,
        "bss_base": bss_base,
        "bss_size": bss_size,
    }


def _evidence_global_layout(module: bytes, entry: dict[str, Any]) -> dict[str, int | str] | None:
    """Derive the rbe global/BSS window only from mutually reinforcing bytes.

    The target code writes a pointer to 0x06040000, later dereferences the
    pointer at 0x06041288, and embeds 0x06047004 as the end address.  The
    latter span is exactly the metadata BSS size.  This is a bounded evidence
    correlation, not a general-purpose address guess; absent all three facts,
    no extra region is mapped.
    """

    if str(entry.get("module")) != "rbe":
        return None
    code_size = int(entry.get("code_size", 0))
    if code_size <= 0 or len(module) < 0x3004:
        return None
    base = 0x06040000
    pointer = base + 0x1288
    runtime_layout = entry.get("runtime_layout") or {}
    bss_size = int(entry.get("bss_size", runtime_layout.get("bss_size", 0)))
    end = base + bss_size
    if bss_size <= 0 or struct.pack("<I", pointer) != module[0x3000:0x3004]:
        return None
    if module.find(struct.pack("<I", base)) < 0:
        return None
    if module.find(struct.pack("<I", end)) < 0:
        return None
    return {
        "base": base,
        "size": bss_size,
        "pointer": pointer,
        "end": end,
        "source": "rbe pointer-table initialization plus metadata BSS-size correlation",
    }


class RealMEImageAttempt:
    """Run a real-byte attempt with explicit, observable stop conditions."""

    def __init__(
        self,
        image_path: Path,
        trace_path: Path | None = None,
        *,
        allow_emulation_auth_bypass: bool = False,
        huffman_dictionary_path: Path | None = None,
    ) -> None:
        self.image_path = Path(image_path)
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self.allow_emulation_auth_bypass = allow_emulation_auth_bypass
        self.huffman_dictionary_path = (
            Path(huffman_dictionary_path)
            if huffman_dictionary_path is not None
            else Path(__file__).resolve().parents[2]
            / "qemu-work"
            / "third-party"
            / "MEAnalyzer"
            / "Huffman.dat"
        )

    def _trace(self, event: dict[str, Any]) -> None:
        if self.trace_path is None:
            return
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def run(self) -> dict[str, Any]:
        try:
            image = self.image_path.read_bytes()
        except OSError as exc:
            return {
                "image": {"path": str(self.image_path)},
                "status": AttemptStatus.PRECHECK_FAILED.value,
                "execution": {
                    "instruction_execution_attempted": False,
                    "bytes_executed": 0,
                    "instructions_executed": 0,
                    "stop_reason": f"cannot read image: {exc}",
                    "trace_path": str(self.trace_path) if self.trace_path else None,
                },
            }

        image_sha256 = hashlib.sha256(image).hexdigest()
        if self.trace_path is not None:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("", encoding="utf-8")
        self._trace(
            {
                "type": "attempt_start",
                "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                "synthetic_model": False,
                "image": str(self.image_path),
                "image_sha256": image_sha256,
            }
        )
        report: dict[str, Any] = {
            "image": {
                "path": str(self.image_path),
                "size": len(image),
                "sha256": image_sha256,
            },
            "status": AttemptStatus.PRECHECK_FAILED.value,
            "mode": "REAL FIRMWARE INSTRUCTION EXECUTION",
            "synthetic_model_used": False,
            "container": {},
            "execution_profile": SKYLAKE_T460_PROFILE.as_dict(),
            "module_plan": None,
            "memory_plan": [],
            "architecture": {
                "isa": "x86-32 module code, based on the public ME 11 loader precedent",
                "endianness": "little",
                "reset_vector": "not present in the external SPI image; supplied by ME ROM",
                "module_format": "Intel ME 11-style descriptor/FPT/FTPR/CPD",
                "compression_flags": {"0": "uncompressed", "2": "Huffman"},
            },
            "entry_metadata": None,
            "authentication": {
                "status": "unknown",
                "bypassed": False,
                "decision": "not available from the preserved SPI dump",
                "hardware_effect": "none; this is not a hardware authentication bypass",
            },
            "validation": {
                "software_checks": [
                    "SPI descriptor/ME region/FPT/FTPR/CPD bounds",
                    "ME11 module stored and uncompressed length bounds",
                    "CSE process-entry range validation",
                    "strict Huffman dictionary and output-length validation",
                    "Unicorn invalid-memory and preserved-SPI write denial",
                ],
                "hardware_enforced_or_external": [
                    "ME ROM reset selector and root-of-trust admission",
                    "signature/decryption state not contained in the external SPI dump",
                ],
                "emulator_only_bypass": "local admission gate, explicit opt-in only",
            },
            "decompression": {
                "attempted": False,
                "status": "not-needed",
                "module": None,
                "dictionary_path": None,
                "dictionary_sha256": None,
                "stored_size": None,
                "uncompressed_size": None,
                "decoded_sha256": None,
                "error": None,
            },
            "emulator": {
                "unicorn_available": UNICORN_AVAILABLE,
                "qemu_host_model": "bounded SPI/PCH/MEI adapter connected to the real-byte runtime",
            },
            "host_model": {
                "spi_reads": "bounded read-only source",
                "pch_registers": "isolated model available",
                "mei_heci": "isolated model available",
                "dma": "deny-by-default bounded grant model",
                "clock_reset_power": "isolated model available",
            },
            "execution": {
                "instruction_execution_attempted": False,
                "bytes_executed": 0,
                "instructions_executed": 0,
                "mmio_accesses": 0,
                "stop_reason": None,
                "trace_path": str(self.trace_path) if self.trace_path else None,
            },
            "warnings": [],
        }

        if self.allow_emulation_auth_bypass:
            report["authentication"] = {
                "status": "emulation-bypassed",
                "bypassed": True,
                "decision": (
                    "explicitly bypassed the local emulator admission gate; no cryptographic "
                    "signature was accepted and physical hardware behavior is unchanged"
                ),
                "hardware_effect": "none; emulator-only experiment",
            }
            self._trace(
                {
                    "type": "authentication_gate",
                    "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                    "synthetic_model": False,
                    "status": "emulation-bypassed",
                    "cryptographic_acceptance": False,
                    "hardware_effect": "none",
                }
            )

        if inspect_ifd is None or inspect_me is None or inspect_cpd is None:
            report["execution"]["stop_reason"] = "parser dependencies unavailable"
            return report

        try:
            ifd = inspect_ifd(self.image_path)
            me = inspect_me(self.image_path)
            cpd = inspect_cpd(self.image_path)
            manifest = inspect_cpd_manifest(self.image_path) if inspect_cpd_manifest else None
        except ValueError as exc:
            report["warnings"].append(str(exc))
            report["execution"]["stop_reason"] = "read-only metadata inspection failed"
            return report

        report["container"] = {
            "ifd": {"descriptor": ifd.get("descriptor"), "regions": ifd.get("regions", []), "warnings": ifd.get("warnings", [])},
            "me": {"me_region": me.get("me_region"), "fpt": me.get("fpt"), "warnings": me.get("warnings", [])},
            "ftpr_cpd": cpd.get("cpd"),
            "ftpr_manifest": (manifest or {}).get("manifest_area"),
        }
        report["warnings"].extend(ifd.get("warnings", []))
        report["warnings"].extend(me.get("warnings", []))
        report["warnings"].extend(cpd.get("warnings", []))
        report["warnings"].extend((manifest or {}).get("warnings", []))

        me_region = me.get("me_region") or {}
        ftpr = next((item for item in (me.get("fpt") or {}).get("partitions", []) if item.get("name") == "FTPR" and item.get("size")), None)
        cpd_result = cpd.get("cpd") or {}
        cpd_entries = cpd_result.get("entries", [])
        if not me_region.get("offset") or not me_region.get("size"):
            report["execution"]["stop_reason"] = "Intel ME region was not identified"
            return report
        if ftpr is None:
            report["execution"]["stop_reason"] = "FTPR partition was not identified"
            return report
        if cpd_result.get("signature") != "$CPD/":
            report["execution"]["stop_reason"] = "FTPR CPD directory was not identified"
            return report

        me_offset = int(me_region["offset"])
        ftpr_offset = int(ftpr["absolute_offset"])
        ftpr_size = int(ftpr["size"])
        report["memory_plan"] = [
            ReadOnlyMapping("me-region-spi-window", me_offset, int(me_region["size"]), 0x10000000, "read-only").as_dict(),
            ReadOnlyMapping("ftpr-partition", ftpr_offset, ftpr_size, 0x10000000 + (ftpr_offset - me_offset), "read-only").as_dict(),
        ]
        report["entry_metadata"] = _metadata_summary(image, ftpr_offset, cpd_entries)
        module_sizes = report["entry_metadata"].get("module_sizes", {})
        report["module_plan"] = build_module_plan(
            cpd_entries=cpd_entries,
            ftpr_absolute_offset=ftpr_offset,
            ftpr_size=ftpr_size,
            me_absolute_offset=me_offset,
            profile=SKYLAKE_T460_PROFILE.name,
            image_size=len(image),
            module_sizes=module_sizes,
        ).as_dict()

        entry_point = (report["entry_metadata"] or {}).get("entry_point")
        if isinstance(entry_point, dict) and isinstance(entry_point.get("address"), int):
            selected_name = entry_point.get("module")
            module_plan = build_module_plan(
                cpd_entries=cpd_entries,
                ftpr_absolute_offset=ftpr_offset,
                ftpr_size=ftpr_size,
                me_absolute_offset=me_offset,
                profile=SKYLAKE_T460_PROFILE.name,
                image_size=len(image),
                module_sizes=module_sizes,
            )
            candidate = next(
                (
                    item
                    for item in module_plan.modules
                    if item.name == selected_name
                ),
                None,
            )
            if candidate is None:
                reason = (
                    f"STOP before instruction fetch: metadata selected module {selected_name!r}, "
                    "but that module is not present in the bounded CPD plan."
                )
            else:
                candidate = replace(candidate, guest_base=int(entry_point["code_base"]))
                try:
                    stored = load_bounded_module(
                        image,
                        replace(candidate, executable_candidate=True),
                        image_sha256=image_sha256,
                    )
                    loaded = stored
                    if candidate.compression == "huffman":
                        report["decompression"].update(
                            {
                                "attempted": True,
                                "status": "running",
                                "module": selected_name,
                                "dictionary_path": str(self.huffman_dictionary_path),
                                "stored_size": candidate.size,
                                "uncompressed_size": candidate.uncompressed_size,
                            }
                        )
                        dictionary = load_me11_dictionary(self.huffman_dictionary_path)
                        decoded = decompress_me11_huffman(
                            stored.data,
                            stored_size=candidate.size,
                            uncompressed_size=candidate.uncompressed_size,
                            dictionary=dictionary,
                        )
                        loaded = load_verified_module_bytes(
                            replace(candidate, guest_base=int(entry_point["code_base"])),
                            decoded,
                            expected_size=candidate.uncompressed_size,
                            valid_extent=int(entry_point.get("code_size", 0)),
                        )
                        report["decompression"].update(
                            {
                                "status": "verified",
                                "dictionary_sha256": dictionary.sha256,
                                "decoded_sha256": loaded.sha256,
                            }
                        )
                        self._trace(
                            {
                                "type": "module_decompressed",
                                "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                                "synthetic_model": False,
                                "module": selected_name,
                                "stored_size": candidate.size,
                                "uncompressed_size": len(decoded),
                                "decoded_sha256": loaded.sha256,
                                "dictionary_sha256": dictionary.sha256,
                            }
                        )
                    if candidate.compression not in ("huffman", "uncompressed"):
                        raise ValueError(
                            f"unsupported selected module compression {candidate.compression}"
                        )
                    if report["authentication"]["status"] not in (
                        "accepted",
                        "emulation-bypassed",
                    ):
                        reason = (
                            "STOP before instruction fetch: the image supplies a bounded module entry "
                            f"({selected_name} at 0x{int(entry_point['address']):x}), but authentication "
                            "has not been cryptographically accepted. Decompression succeeded; no "
                            "security check was bypassed."
                        )
                        report["status"] = AttemptStatus.STOPPED_BEFORE_EXECUTION.value
                        report["execution"]["stop_reason"] = reason
                        self._trace(
                            {
                                "type": "stop",
                                "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                                "synthetic_model": False,
                                "instructions": 0,
                                "stop_reason": reason,
                            }
                        )
                        return report
                    code_size = int(entry_point.get("code_size", 0))
                    if code_size > len(loaded.data):
                        raise ValueError(
                            f"module entry metadata requires 0x{code_size:x} bytes of code, "
                            f"but decoded bytes contain only 0x{len(loaded.data):x}"
                        )
                    entry_offset = int(entry_point.get("offset", 0))
                    if entry_offset < 0 or entry_offset >= len(loaded.data):
                        raise ValueError(
                            f"entry offset 0x{entry_offset:x} is outside loaded module bytes"
                        )
                    runtime_layout = entry_point.get("runtime_layout")
                    runtime_config = RealRuntimeConfig()
                    if isinstance(runtime_layout, dict):
                        runtime_layout = dict(runtime_layout)
                        evidence_global = _evidence_global_layout(loaded.data, entry_point)
                        if evidence_global is not None:
                            runtime_layout["evidence_global_base"] = evidence_global["base"]
                            runtime_layout["evidence_global_size"] = evidence_global["size"]
                        runtime_config = RealRuntimeConfig(
                            stack_base=int(runtime_layout["stack_base"]),
                            stack_size=int(runtime_layout["stack_size"]),
                            stack_top=int(runtime_layout["stack_top"]),
                            module_heap_base=int(runtime_layout["heap_base"]),
                            module_heap_size=int(runtime_layout["heap_size"]),
                            module_bss_base=int(runtime_layout["bss_base"]),
                            module_bss_size=int(runtime_layout["bss_size"]),
                            evidence_global_base=(
                                int(runtime_layout["evidence_global_base"])
                                if "evidence_global_base" in runtime_layout
                                else None
                            ),
                            evidence_global_size=int(runtime_layout.get("evidence_global_size", 0)),
                        )
                    runtime = RealUnicornRuntime(
                        image=image,
                        image_sha256=image_sha256,
                        trace_path=self.trace_path or self.image_path.with_suffix(".trace.jsonl"),
                        config=runtime_config,
                    )
                    result = runtime.run(loaded, int(entry_point.get("offset", 0)))
                    report["execution"].update(result)
                    report["status"] = (
                        AttemptStatus.EXECUTION_COMPLETED.value
                        if result.get("stop_reason") == "emulator returned"
                        else AttemptStatus.EXECUTION_STOPPED.value
                    )
                    return report
                except HuffmanDecodeError as exc:
                    report["decompression"].update(
                        {"attempted": True, "status": "failed", "error": str(exc)}
                    )
                    report["status"] = AttemptStatus.STOPPED_BEFORE_EXECUTION.value
                    report["execution"]["stop_reason"] = (
                        f"STOP before instruction fetch: verified ME11 Huffman decompression failed: {exc}"
                    )
                    return report
                except Exception as exc:
                    report["status"] = AttemptStatus.EXECUTION_STOPPED.value
                    report["execution"]["stop_reason"] = f"real runtime setup failed: {exc}"
                    return report
        else:
            reason = (
                "STOP before instruction fetch: no bounded firmware entry metadata is available "
                "from the preserved SPI image. The ME reset ROM/library remains image-external."
            )
        report["status"] = AttemptStatus.STOPPED_BEFORE_EXECUTION.value
        report["execution"]["stop_reason"] = reason
        self._trace(
            {
                "type": "stop",
                "domain": "REAL FIRMWARE INSTRUCTION EXECUTION",
                "synthetic_model": False,
                "instructions": 0,
                "stop_reason": reason,
            }
        )
        return report


__all__ = ["AttemptStatus", "ReadOnlyMapping", "RealMEImageAttempt"]
