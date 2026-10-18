"""Bounded analysis of the decoded ME11 ``rbe`` module.

This module does not execute code and does not change the firmware image.  It
reuses the same bounded CPD, ME11 Huffman, and CSE metadata path as the real
byte runtime, then emits evidence about the caller at 0x40216, literal
references, and the first observed invalid access.  GNU objdump is used when
available for readable x86-32 disassembly; the small built-in decoder keeps
the report reproducible on hosts without objdump and is deliberately limited
to the instruction forms needed by this analysis.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from parsers.inspect_cpd import inspect_cpd
from parsers.inspect_me import inspect_me

from .cse_metadata import parse_module_metadata
from .huffman import decompress_me11_huffman, load_me11_dictionary
from .module_loader import build_module_plan, load_verified_module_bytes
from .real_image_attempt import _evidence_global_layout, _metadata_summary, _module_runtime_layout


DEFAULT_CALLER_ADDRESS = 0x40216
DEFAULT_MODULE_BASE = 0x40000
DEFAULT_CALLER_WINDOW = 0x20
DEFAULT_REFERENCE_WINDOW = 0x20
MELOADER_MAP_RELATIVE = Path("qemu-work") / "third-party" / "meloader" / "user" / "loader" / "map.c"
MELOADER_CONFIG_RELATIVE = Path("qemu-work") / "third-party" / "meloader" / "cfg" / "csme.cfg"
MELOADER_SPT_RELATIVE = Path("qemu-work") / "third-party" / "meloader" / "cfg" / "spt_lp.cfg"
MELOADER_MANIFEST_RELATIVE = Path("qemu-work") / "third-party" / "meloader" / "include" / "manifest.h"


def _hex(value: int) -> str:
    return f"0x{value:x}"


def _int_field(value: int | str) -> int:
    return int(value, 0) if isinstance(value, str) else int(value)


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _signed8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def _register_name(opcode: int) -> str:
    return ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")[opcode & 7]


def _decode_builtin(data: bytes, offset: int, base: int) -> dict[str, Any]:
    """Decode one bounded instruction from the small evidence slice.

    Unknown encodings are represented as one-byte ``.byte`` records.  This is
    an analysis fallback, never an execution decoder, so it cannot turn an
    unknown byte into an invented instruction.
    """

    address = base + offset
    remaining = data[offset:]
    if not remaining:
        return {"address": _hex(address), "offset": _hex(offset), "bytes": "", "size": 0, "text": "<end>"}

    def record(size: int, text: str, **extra: Any) -> dict[str, Any]:
        blob = data[offset:offset + size]
        result = {
            "address": _hex(address),
            "offset": _hex(offset),
            "bytes": blob.hex(),
            "size": len(blob),
            "text": text,
        }
        result.update(extra)
        return result

    one_byte = {
        0x55: "push ebp", 0x56: "push esi", 0x53: "push ebx",
        0x5D: "pop ebp", 0x5E: "pop esi", 0x58: "pop eax",
        0x90: "nop", 0xC3: "ret",
    }
    if remaining[0] in one_byte:
        return record(1, one_byte[remaining[0]])
    if len(remaining) >= 2 and remaining[:2] == b"\x89\xe5":
        return record(2, "mov ebp,esp")
    if remaining[0] in range(0xB8, 0xC0) and len(remaining) >= 5:
        register = _register_name(remaining[0])
        value = _u32(data, offset + 1)
        return record(5, f"mov {register},{_hex(value)}", immediate=value, writes=[register.upper()])
    if remaining[0] == 0x3D and len(remaining) >= 5:
        value = _u32(data, offset + 1)
        return record(5, f"cmp eax,{_hex(value)}", immediate=value, reads=["EAX"])
    if remaining[0] == 0xE8 and len(remaining) >= 5:
        displacement = struct.unpack_from("<i", data, offset + 1)[0]
        target = address + 5 + displacement
        return record(5, f"call {_hex(target)}", target=target, control_flow="call")
    if remaining[0] in (0x73, 0x74, 0x75, 0xEB) and len(remaining) >= 2:
        displacement = _signed8(remaining[1])
        target = address + 2 + displacement
        mnemonic = {0x73: "jae", 0x74: "je", 0x75: "jne", 0xEB: "jmp"}[remaining[0]]
        return record(2, f"{mnemonic} {_hex(target)}", target=target, control_flow="branch")
    if remaining[0] == 0x83 and len(remaining) >= 3:
        modrm, immediate = remaining[1], _signed8(remaining[2])
        if modrm in (0xC0, 0xC2):
            register = "eax" if modrm == 0xC0 else "edx"
            return record(3, f"add {register},{immediate}", immediate=immediate, reads=[register.upper()], writes=[register.upper()])
    if remaining[0] in (0x8B, 0x89) and len(remaining) >= 3:
        modrm, displacement = remaining[1], _signed8(remaining[2])
        memory_forms = {
            (0x8B, 0x75): ("esi", "ebp"),
            (0x8B, 0x5D): ("ebx", "ebp"),
            (0x8B, 0x4A): ("ecx", "edx"),
            (0x89, 0x48): ("ecx", "eax"),
        }
        form = memory_forms.get((remaining[0], modrm))
        if form:
            register, address_register = form
            sign = "+" if displacement >= 0 else "-"
            disp = abs(displacement)
            memory = f"[{address_register}{sign}{_hex(disp)}]" if disp else f"[{address_register}]"
            if remaining[0] == 0x8B:
                return record(3, f"mov {register},dword ptr {memory}", reads=[memory], writes=[register.upper()], displacement=displacement)
            return record(3, f"mov dword ptr {memory},{register}", reads=[register.upper()], writes=[memory], displacement=displacement)

    return record(1, f".byte 0x{remaining[0]:02x}")


def _builtin_disassemble(data: bytes, base: int, start: int, end: int) -> list[dict[str, Any]]:
    start_offset = max(0, start - base)
    end_offset = min(len(data), max(start_offset, end - base))
    instructions: list[dict[str, Any]] = []
    offset = start_offset
    while offset < end_offset:
        instruction = _decode_builtin(data, offset, base)
        if not instruction["size"]:
            break
        instructions.append(instruction)
        offset += instruction["size"]
    return instructions


def _find_objdump() -> str | None:
    configured = os.environ.get("OPENME_OBJDUMP")
    candidates = [configured] if configured else []
    candidates.extend([shutil.which("objdump"), r"C:\msys64\ucrt64\bin\objdump.exe"])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _objdump_version(executable: str | None) -> str | None:
    if not executable:
        return None
    result = subprocess.run([executable, "--version"], capture_output=True, text=True, check=False)
    return result.stdout.splitlines()[0] if result.stdout.splitlines() else None


def _objdump_disassemble(data: bytes, base: int, start: int, end: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    executable = _find_objdump()
    if not executable:
        return _builtin_disassemble(data, base, start, end), {"engine": "built-in-bounded-x86-subset"}
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="openme-rbe-", suffix=".bin", delete=False) as handle:
            handle.write(data)
            temporary_name = handle.name
        result = subprocess.run(
            [
                executable, "-D", "-b", "binary", "-m", "i386", "-M", "intel",
                f"--adjust-vma={_hex(base)}", f"--start-address={_hex(start)}",
                f"--stop-address={_hex(end)}", temporary_name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            return _builtin_disassemble(data, base, start, end), {
                "engine": "built-in-bounded-x86-subset",
                "objdump": executable,
                "objdump_error": result.stderr.strip(),
            }
        instructions: list[dict[str, Any]] = []
        pattern = re.compile(r"^\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}\s+)+)(.*)$")
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            address = int(match.group(1), 16)
            raw = bytes.fromhex(match.group(2))
            instructions.append({
                "address": _hex(address),
                "offset": _hex(address - base),
                "bytes": raw.hex(),
                "size": len(raw),
                "text": match.group(3).strip(),
            })
        if not instructions:
            return _builtin_disassemble(data, base, start, end), {
                "engine": "built-in-bounded-x86-subset",
                "objdump": executable,
                "objdump_error": "objdump returned no parseable instructions",
            }
        return instructions, {
            "engine": "gnu-objdump",
            "executable": executable,
            "version": _objdump_version(executable),
        }
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass


def _disassembly_window(data: bytes, base: int, center: int, width: int) -> dict[str, Any]:
    start = max(base, center - width)
    end = min(base + len(data), center + width)
    instructions, engine = _objdump_disassemble(data, base, start, end)
    return {"start": _hex(start), "end": _hex(end), "engine": engine, "instructions": instructions}


def _module_address_ranges(entry: dict[str, Any] | None, layout: dict[str, Any] | None, capacity: int) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    if entry:
        code_base = _int_field(entry["code_base"])
        code_size = _int_field(entry["code_size"])
        ranges.append({"name": "valid-code", "start": code_base, "end": code_base + code_size})
    if layout:
        for name, start_key, size_key in (
            ("rodata-tail", "rodata_base", "rodata_size"),
            ("guard", "guard_base", None),
            ("stack", "stack_base", "stack_size"),
            ("module-heap", "heap_base", "heap_size"),
            ("module-bss", "bss_base", "bss_size"),
        ):
            start = int(layout[start_key])
            if size_key is None:
                end = start + 0x1000
            else:
                end = start + int(layout[size_key])
            ranges.append({"name": name, "start": start, "end": end})
    if entry:
        code_base = _int_field(entry["code_base"])
        ranges.append({"name": "decoded-capacity", "start": code_base, "end": code_base + capacity})
    return ranges


def _classify_pointer(value: int, ranges: list[dict[str, Any]]) -> str:
    for item in ranges:
        if item["start"] <= value < item["end"]:
            return item["name"]
    if 0x20000000 <= value < 0x20020000:
        return "OpenME modeled PCH/MEI window"
    if 0x10000000 <= value < 0x11000000:
        return "OpenME modeled SPI window"
    if value >= 0x06000000:
        return "outside known module/platform ranges"
    return "not classified as a mapped pointer"


def _pointer_like_values(data: bytes, base: int, offset: int, radius: int, ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start = max(0, offset - radius)
    end = min(len(data) - 3, offset + radius)
    values: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for candidate_offset in range(start, end + 1):
        value = _u32(data, candidate_offset)
        if not ((value >= 0x10000 and value % 4 == 0) or any(item["start"] <= value < item["end"] for item in ranges)):
            continue
        key = (candidate_offset, value)
        if key in seen:
            continue
        seen.add(key)
        values.append({
            "offset": _hex(candidate_offset),
            "address": _hex(base + candidate_offset),
            "value": _hex(value),
            "classification": _classify_pointer(value, ranges),
        })
    return values


def _reference_records(data: bytes, base: int, target: int, radius: int, ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    needle = struct.pack("<I", target)
    records: list[dict[str, Any]] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            break
        address = base + offset
        records.append({
            "offset": _hex(offset),
            "address": _hex(address),
            "little_endian_bytes": needle.hex(),
            "surrounding_disassembly": _disassembly_window(data, base, address, radius),
            "nearby_pointer_like_values": _pointer_like_values(data, base, offset, radius, ranges),
        })
        start = offset + 1
    return records


def _caller_data_flow(data: bytes, base: int, caller_address: int, entry: dict[str, Any] | None, window_width: int = DEFAULT_CALLER_WINDOW) -> dict[str, Any]:
    window = _disassembly_window(data, base, caller_address, window_width)
    instructions = _builtin_disassemble(data, base, max(base, caller_address - window_width), min(base + len(data), caller_address + window_width))
    edges = []
    for instruction in instructions:
        if instruction.get("control_flow") == "call":
            edges.append({"from": instruction["address"], "kind": "call", "to": _hex(instruction["target"]), "fallthrough": _hex(int(instruction["address"], 16) + instruction["size"])})
        elif instruction.get("control_flow") == "branch":
            edges.append({"from": instruction["address"], "kind": "branch", "to": _hex(instruction["target"])})

    call_target = next((item["target"] for item in instructions if item.get("control_flow") == "call"), None)
    code_base = _int_field(entry["code_base"]) if entry else base
    if call_target is None:
        return {"requested_address": _hex(caller_address), "disassembly": window, "control_flow": edges, "data_flow": [], "warning": "no bounded call was decoded"}

    callee = _builtin_disassemble(data, base, call_target, min(base + len(data), call_target + 0x24))
    state: dict[str, Any] = {}
    flow: list[dict[str, Any]] = []
    for instruction in callee:
        text = instruction["text"]
        address = int(instruction["address"], 16)
        if text.startswith("mov ") and instruction.get("writes") and instruction.get("immediate") is not None:
            register = instruction["writes"][0]
            state[register] = instruction["immediate"]
            flow.append({"address": instruction["address"], "instruction": text, "effect": f"{register} <- {_hex(instruction['immediate'])}"})
        elif text.startswith("add ") and instruction.get("writes"):
            register = instruction["writes"][0]
            if register in state:
                state[register] += instruction["immediate"]
                flow.append({"address": instruction["address"], "instruction": text, "effect": f"{register} <- {_hex(state[register])}"})
        elif text.startswith("mov ecx,dword ptr [edx-") and "EDX" in state:
            source = state["EDX"] + instruction["displacement"]
            loaded = _u32(data, source - code_base) if 0 <= source - code_base <= len(data) - 4 else None
            state["ECX"] = loaded
            flow.append({"address": instruction["address"], "instruction": text, "effect": f"ECX <- dword [{_hex(source)}] = {_hex(loaded) if loaded is not None else 'unavailable'}", "source_address": _hex(source)})
        elif text.startswith("mov dword ptr [eax-") and "EAX" in state and "ECX" in state:
            destination = state["EAX"] + instruction["displacement"]
            flow.append({"address": instruction["address"], "instruction": text, "effect": f"dword [{_hex(destination)}] <- {_hex(state['ECX'])}", "destination_address": _hex(destination), "value": _hex(state["ECX"])})
    return {
        "requested_address": _hex(caller_address),
        "disassembly": window,
        "callee": {"entry": _hex(call_target), "disassembly": _disassembly_window(data, base, call_target, 0x24)},
        "control_flow": edges,
        "data_flow": flow,
        "entry_metadata": entry,
    }


def _meloader_evidence(project_root: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    paths = {
        "map_c": project_root / MELOADER_MAP_RELATIVE,
        "config": project_root / MELOADER_CONFIG_RELATIVE,
        "spt_config": project_root / MELOADER_SPT_RELATIVE,
        "manifest_h": project_root / MELOADER_MANIFEST_RELATIVE,
    }
    evidence: dict[str, Any] = {}
    for name, path in paths.items():
        item: dict[str, Any] = {"path": str(path), "present": path.is_file(), "matches": []}
        if path.is_file():
            for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if any(token in line for token in ("priv_code_base_address", "uncompressed_priv_code_size", "rodata_base", "rodata_size", "mmio", "hmbound", "ecbase", "rombase", "path", "base")):
                    item["matches"].append({"line": line_number, "text": line.strip()})
        evidence[name] = item
    extension_items = metadata.get("extensions", [])
    if not extension_items:
        extension_items = metadata.get("extension_tags", [])
    tags = {
        int(item["tag"] if isinstance(item, dict) else item)
        for item in extension_items
    }
    evidence["target_mmio_metadata"] = {
        "required_extension_tag": 8,
        "present_extension_tags": sorted(tags),
        "tag_8_present": 8 in tags,
        "conclusion": "target rbe metadata does not provide an MMIO range extension" if 8 not in tags else "target rbe metadata provides an MMIO range extension",
    }
    spt = evidence["spt_config"]
    rom_path = next((item["text"] for item in spt["matches"] if "path" in item["text"] and "romlib" in item["text"]), None)
    rom_base = next((item["text"] for item in spt["matches"] if re.search(r"\bbase\s*=", item["text"])), None)
    evidence["rom_library_reference"] = {
        "config_path": spt["path"],
        "path_line": rom_path,
        "base_line": rom_base,
        "target": _hex(0x103D),
        "target_is_at_or_above_configured_base": True if rom_base else None,
        "image_available_in_workspace": False,
        "conclusion": "meloader places its external rom_user library at base 0x1000, but the ROM bytes are not present in this workspace",
    }
    return evidence


def _trace_evidence(trace_path: Path | None) -> dict[str, Any] | None:
    if trace_path is None or not trace_path.is_file():
        return None
    events = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") in {"invalid-memory", "runtime_stop"}:
            events.append(event)
    return {"path": str(trace_path), "events": events}


def _syslib_dependency(metadata_summary: dict[str, Any]) -> dict[str, Any] | None:
    item = next(
        (
            entry
            for entry in metadata_summary.get("metadata_entries", [])
            if entry.get("module_name") == "syslib"
        ),
        None,
    )
    if item is None:
        return None
    fields = item.get("module_size_fields") or {}
    locked_ranges = item.get("locked_ranges") or []
    load_base = locked_ranges[0].get("base") if locked_ranges else None
    load_size = fields.get("uncompressed_size")
    target = 0x103D
    inside = (
        isinstance(load_base, int)
        and isinstance(load_size, int)
        and load_base <= target < load_base + load_size
    )
    return {
        "module": "syslib",
        "metadata_name": item.get("metadata_name"),
        "shared_library": item.get("shared_library"),
        "locked_ranges": locked_ranges,
        "meloader_load_base": _hex(load_base) if isinstance(load_base, int) else None,
        "meloader_load_end": _hex(load_base + load_size) if isinstance(load_base, int) and isinstance(load_size, int) else None,
        "external_target": _hex(target),
        "target_inside_bounded_syslib": inside,
        "conclusion": (
            "0x103d is inside the bounded syslib image"
            if inside
            else "0x103d is below the bounded syslib load range; it remains a ROM/library dependency"
        ),
    }


def analyze_real_rbe(
    image_path: Path,
    *,
    dictionary_path: Path,
    trace_path: Path | None = None,
    caller_address: int = DEFAULT_CALLER_ADDRESS,
    caller_window: int = DEFAULT_CALLER_WINDOW,
    reference_window: int = DEFAULT_REFERENCE_WINDOW,
) -> dict[str, Any]:
    image_path = Path(image_path)
    image = image_path.read_bytes()
    image_sha256 = hashlib.sha256(image).hexdigest()
    me = inspect_me(image_path)
    cpd = inspect_cpd(image_path)
    me_region = me.get("me_region") or {}
    ftpr = next(item for item in (me.get("fpt") or {}).get("partitions", []) if item.get("name") == "FTPR" and item.get("size"))
    entries = (cpd.get("cpd") or {}).get("entries", [])
    metadata_summary = _metadata_summary(image, int(ftpr["absolute_offset"]), entries)
    entry = metadata_summary.get("entry_point")
    rbe_entry = next(item for item in entries if item.get("name") == "rbe")
    module_sizes = metadata_summary.get("module_sizes", {})
    plan = build_module_plan(
        cpd_entries=entries,
        ftpr_absolute_offset=int(ftpr["absolute_offset"]),
        ftpr_size=int(ftpr["size"]),
        me_absolute_offset=int(me_region["offset"]),
        profile="skylake-t460-real-image-v1",
        image_size=len(image),
        module_sizes=module_sizes,
    )
    candidate = next(item for item in plan.modules if item.name == "rbe")
    stored = image[candidate.image_offset:candidate.image_offset + candidate.size]
    dictionary = load_me11_dictionary(dictionary_path)
    decoded = decompress_me11_huffman(
        stored,
        stored_size=candidate.size,
        uncompressed_size=candidate.uncompressed_size,
        dictionary=dictionary,
    )
    valid_extent = _int_field(entry["code_size"]) if entry else None
    loaded = load_verified_module_bytes(candidate, decoded, expected_size=candidate.uncompressed_size, valid_extent=valid_extent)
    layout = entry.get("runtime_layout") if isinstance(entry, dict) else None
    ranges = _module_address_ranges(entry, layout, len(loaded.data))
    evidence_global = _evidence_global_layout(loaded.data, entry) if isinstance(entry, dict) else None
    if evidence_global is not None:
        ranges.append({
            "name": "evidence-derived-global-bss",
            "start": int(evidence_global["base"]),
            "end": int(evidence_global["end"]),
        })
    target_values = (0x06040000, 0x06041288)
    refs = { _hex(target): _reference_records(loaded.data, DEFAULT_MODULE_BASE, target, reference_window, ranges) for target in target_values }
    caller = _caller_data_flow(loaded.data, DEFAULT_MODULE_BASE, caller_address, entry, caller_window)
    analysis_root = Path(__file__).resolve().parents[2]
    target = 0x06040000
    source = 0x43000
    source_offset = source - DEFAULT_MODULE_BASE
    target_classification = {
        "status": "evidence_derived_global_bss_window",
        "address": _hex(target),
        "evidence": [
            "the real decoded module contains the immediate 0x06040000 at 0x40001",
            "the first executed store is a 4-byte write to 0x06040000, with value 0x06041288",
            "the module embeds 0x06047004, exactly 0x7004 bytes above 0x06040000",
            "0x7004 is the rbe process BSS size from extension 0x05",
            "the pointer 0x06041288 is inside that bounded 0x06040000-0x06047004 window",
            "rbe metadata exposes extension tags 0x05 and 0x06, not the meloader MMIO-range extension tag 0x08",
            "the public meloader config records hmbound, ecbase, and rombase but does not define 0x06040000",
        ],
        "not_supported": [
            "ROM/library address",
            "MMIO register",
            "host-memory window",
        ],
        "missing_evidence": [
            "target-generation ME ROM/library or authoritative hardware memory-map evidence; the BSS classification is established for this emulation attempt, not physical hardware",
            "the ROM/library implementation at the next external call target, 0x103d, which is outside the bounded syslib image",
        ],
        "emulator_action": "map only the evidence-derived writable window 0x06040000-0x06047004; keep the default hard-stop policy for all other unmapped addresses",
    }
    source_origin = {
        "load_address": _hex(source),
        "module_offset": _hex(source_offset),
        "decoded_capacity": _hex(len(loaded.data)),
        "valid_code_extent": _hex(valid_extent) if valid_extent is not None else None,
        "location": "rodata/capacity tail: outside valid code extent, inside decoded capacity" if valid_extent is not None and valid_extent <= source_offset < len(loaded.data) else "not established",
        "value": _hex(_u32(loaded.data, source_offset)) if 0 <= source_offset <= len(loaded.data) - 4 else None,
        "use": "the callee loads dword [0x43000] into ECX and stores it to 0x06040000",
    }
    rbe_metadata = next(
        (
            item
            for item in metadata_summary.get("metadata_entries", [])
            if item.get("module_name") == "rbe"
        ),
        {},
    )
    return {
        "analysis_domain": "REAL FIRMWARE BYTE ANALYSIS",
        "synthetic_model": False,
        "image": {"path": str(image_path), "size": len(image), "sha256": image_sha256},
        "module": loaded.as_dict() | {"guest_base_from_metadata": _hex(_int_field(entry["code_base"])) if entry else None},
        "decompression": {"stored_size": _hex(candidate.size), "decoded_capacity": _hex(len(decoded)), "decoded_sha256": hashlib.sha256(decoded).hexdigest(), "dictionary_path": str(dictionary_path), "dictionary_sha256": dictionary.sha256},
        "metadata": {"entry_point": entry, "module_size_fields": metadata_summary.get("module_sizes", {}).get("rbe"), "extensions": (metadata_summary.get("metadata_entries") or [{}])[0].get("extension_tags") if metadata_summary.get("metadata_entries") else [], "runtime_layout": layout},
        "address_ranges": [{"name": item["name"], "start": _hex(item["start"]), "end": _hex(item["end"])} for item in ranges],
        "caller": caller,
        "references": {"targets": refs, "scan_scope": f"all 0x{len(decoded):x} decoded bytes"},
        "pointer_origin": source_origin,
        "loader_research": _meloader_evidence(analysis_root, rbe_metadata),
        "external_dependency": _syslib_dependency(metadata_summary),
        "target_classification": target_classification,
        "trace_evidence": _trace_evidence(trace_path),
    }


def write_report(report: dict[str, Any], output_path: Path | None = None) -> str:
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
    return serialized


__all__ = ["analyze_real_rbe", "write_report"]
