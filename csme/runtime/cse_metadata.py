"""Bounded parsing of CSME 11 module process metadata.

The process-attributes extension is the image's own module entry metadata.
This parser records it only after validating the extension size and the
entry-point range; it does not infer a reset vector or alter authentication.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any


METADATA_HEADER_SIZE = 0x38
EXTENSION_HEADER_SIZE = 0x08
PROCESS_ATTRIBUTES_TAG = 0x05
PROCESS_ATTRIBUTES_MIN_SIZE = 0x2C


@dataclass(frozen=True)
class ProcessAttributes:
    extension_offset: int
    extension_size: int
    flags: int
    main_thread_id: int
    code_base: int
    code_size: int
    bss_size: int
    default_heap_size: int
    main_thread_entry: int
    entry_offset: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "extension_offset": f"0x{self.extension_offset:x}",
            "extension_size": f"0x{self.extension_size:x}",
            "flags": f"0x{self.flags:x}",
            "main_thread_id": f"0x{self.main_thread_id:x}",
            "code_base": f"0x{self.code_base:x}",
            "code_size": f"0x{self.code_size:x}",
            "bss_size": f"0x{self.bss_size:x}",
            "default_heap_size": f"0x{self.default_heap_size:x}",
            "main_thread_entry": f"0x{self.main_thread_entry:x}",
            "entry_offset": None if self.entry_offset is None else f"0x{self.entry_offset:x}",
            "entry_in_code_range": self.entry_offset is not None,
        }


def parse_module_metadata(blob: bytes) -> dict[str, Any]:
    """Parse bounded extension headers and process attributes from one `.met`."""

    result: dict[str, Any] = {
        "extensions": [],
        "process_attributes": [],
        "thread_info": [],
        "shared_library": None,
        "locked_ranges": [],
        "module_size_fields": None,
        "warnings": [],
    }
    if len(blob) < METADATA_HEADER_SIZE:
        result["warnings"].append("metadata header is truncated")
        return result

    result["module_size_fields"] = {
        "uncompressed_size": int.from_bytes(blob[0x0C:0x10], "little"),
        "stored_size": int.from_bytes(blob[0x10:0x14], "little"),
        "source": "bounded ME11 module metadata header fields",
    }

    cursor = METADATA_HEADER_SIZE
    while cursor + EXTENSION_HEADER_SIZE <= len(blob):
        tag, size = struct.unpack_from("<II", blob, cursor)
        if size < EXTENSION_HEADER_SIZE:
            result["warnings"].append(
                f"extension 0x{tag:x} at 0x{cursor:x} has an invalid size 0x{size:x}"
            )
            break
        end = cursor + size
        if end > len(blob):
            result["warnings"].append(
                f"extension 0x{tag:x} at 0x{cursor:x} exceeds metadata bounds"
            )
            break
        result["extensions"].append({"tag": tag, "offset": cursor, "size": size})

        if tag == PROCESS_ATTRIBUTES_TAG:
            if size < PROCESS_ATTRIBUTES_MIN_SIZE:
                result["warnings"].append(
                    f"process attributes at 0x{cursor:x} are truncated"
                )
            else:
                values = struct.unpack_from("<8I", blob, cursor + EXTENSION_HEADER_SIZE)
                _, main_thread_id, code_base, code_size, _cm0_heap, bss_size, default_heap, entry = values
                entry_offset = None
                if code_base <= entry < code_base + code_size:
                    entry_offset = entry - code_base
                result["process_attributes"].append(
                    ProcessAttributes(
                        extension_offset=cursor,
                        extension_size=size,
                        flags=values[0],
                        main_thread_id=main_thread_id,
                        code_base=code_base,
                        code_size=code_size,
                        bss_size=bss_size,
                        default_heap_size=default_heap,
                        main_thread_entry=entry,
                        entry_offset=entry_offset,
                    ).as_dict()
                )
        elif tag == 0x06:
            # ME11 thread extension: one or more 12-byte man_thread records.
            # Preserve any trailing bytes as a warning rather than guessing a
            # second structure layout.
            payload_size = size - EXTENSION_HEADER_SIZE
            thread_count = payload_size // 12
            if payload_size % 12:
                result["warnings"].append(
                    f"thread extension at 0x{cursor:x} has {payload_size % 12} trailing bytes"
                )
            for index in range(thread_count):
                offset = cursor + EXTENSION_HEADER_SIZE + index * 12
                stack_size, flags, scheduling_policy = struct.unpack_from(
                    "<3I", blob, offset
                )
                result["thread_info"].append(
                    {
                        "index": index,
                        "stack_size": stack_size,
                        "flags": flags,
                        "scheduling_policy": scheduling_policy,
                    }
                )
        elif tag == 0x04:
            if size < 0x1C:
                result["warnings"].append(
                    f"shared-library extension at 0x{cursor:x} is truncated"
                )
            else:
                context_size, total_alloc_virtual_space, code_base_address, tls_size, reserved = struct.unpack_from(
                    "<5I", blob, cursor + EXTENSION_HEADER_SIZE
                )
                result["shared_library"] = {
                    "context_size": context_size,
                    "total_alloc_virtual_space": total_alloc_virtual_space,
                    "code_base_address": code_base_address,
                    "tls_size": tls_size,
                    "reserved": reserved,
                }
        elif tag == 0x0B:
            payload_size = size - EXTENSION_HEADER_SIZE
            if payload_size % 8:
                result["warnings"].append(
                    f"locked-ranges extension at 0x{cursor:x} has {payload_size % 8} trailing bytes"
                )
            for index in range(payload_size // 8):
                offset = cursor + EXTENSION_HEADER_SIZE + index * 8
                base, range_size = struct.unpack_from("<2I", blob, offset)
                result["locked_ranges"].append(
                    {"index": index, "base": base, "size": range_size}
                )
        cursor = end

    return result


__all__ = [
    "METADATA_HEADER_SIZE",
    "PROCESS_ATTRIBUTES_TAG",
    "ProcessAttributes",
    "parse_module_metadata",
]
