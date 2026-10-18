"""Strict Intel ME11 Huffman module decompression.

ME11 CPD entries marked with offset-attribute bit 25 contain a small table of
chunk offsets followed by Huffman-coded module data.  The dictionary is the
public MEAnalyzer ME11 dictionary; it is treated as input data and hashed in
the execution report.  This module never pads, guesses, or emits replacement
bytes: malformed tables, unknown dictionary symbols, truncated bit streams,
and output-length mismatches are hard failures.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


CHUNK_SIZE = 0x1000
HUFFMAN_OFFSET_FLAG = 1 << 25
HUFFMAN_OFFSET_MASK = HUFFMAN_OFFSET_FLAG - 1


class HuffmanDecodeError(ValueError):
    """The bounded ME11 Huffman container cannot be decoded safely."""


@dataclass(frozen=True)
class ME11HuffmanDictionary:
    path: Path
    sha256: str
    tables: dict[int, dict[str, bytes]]


def load_me11_dictionary(path: Path) -> ME11HuffmanDictionary:
    """Load the ME11 dictionary and retain its reproducibility hash."""

    path = Path(path)
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
        root = document["11"]
        tables: dict[int, dict[str, bytes]] = {}
        # ME11 Huffman headers use 0x20 for codewords and 0x60 for data.
        # The dictionary file stores those tables by semantic name.
        for dictionary_type, name in ((0x20, "code"), (0x60, "data")):
            source = root[name]
            table: dict[str, bytes] = {}
            for bit_string, hex_string in source.items():
                if not isinstance(bit_string, str) or not bit_string or any(
                    bit not in "01" for bit in bit_string
                ):
                    raise HuffmanDecodeError(
                        f"{path}: invalid {name} dictionary key {bit_string!r}"
                    )
                if not isinstance(hex_string, str) or len(hex_string) % 2:
                    raise HuffmanDecodeError(
                        f"{path}: invalid {name} symbol for {bit_string!r}"
                    )
                try:
                    table[bit_string] = bytes.fromhex(hex_string)
                except ValueError as exc:
                    raise HuffmanDecodeError(
                        f"{path}: invalid {name} symbol for {bit_string!r}"
                    ) from exc
            if not table:
                raise HuffmanDecodeError(f"{path}: empty {name} dictionary")
            tables[dictionary_type] = table
        return ME11HuffmanDictionary(
            path=path,
            sha256=hashlib.sha256(raw).hexdigest(),
            tables=tables,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HuffmanDecodeError(f"cannot load ME11 dictionary {path}: {exc}") from exc


def _read_header(module: bytes, output_size: int, stored_size: int) -> tuple[list[int], int]:
    if output_size <= 0 or stored_size <= 0:
        raise HuffmanDecodeError("ME11 Huffman sizes must be positive")
    if output_size % CHUNK_SIZE:
        raise HuffmanDecodeError(
            f"ME11 Huffman output size 0x{output_size:x} is not chunk aligned"
        )
    chunk_count = output_size // CHUNK_SIZE
    header_size = chunk_count * 4
    if stored_size > len(module) or header_size > stored_size:
        raise HuffmanDecodeError(
            f"ME11 Huffman header size 0x{header_size:x} exceeds stored size 0x{stored_size:x}"
        )
    offsets: list[int] = []
    for index in range(chunk_count):
        packed = struct.unpack_from("<I", module, index * 4)[0]
        dictionary_type = (packed >> 25) & 0x7F
        offset = packed & HUFFMAN_OFFSET_MASK
        if dictionary_type not in (0x20, 0x60):
            raise HuffmanDecodeError(
                f"chunk {index}: unsupported ME11 dictionary type 0x{dictionary_type:x}"
            )
        if offset > stored_size - header_size:
            raise HuffmanDecodeError(
                f"chunk {index}: offset 0x{offset:x} exceeds compressed payload"
            )
        offsets.append((dictionary_type << 25) | offset)
    return offsets, header_size


def _decode_chunk(
    compressed: bytes,
    dictionary: dict[str, bytes],
    expected_output_size: int,
    *,
    chunk_index: int,
) -> bytes:
    output = bytearray()
    bit_buffer = 0
    available_bits = 0
    compressed_position = 0
    current_bits = ""
    while len(output) < expected_output_size:
        while available_bits < 32 and compressed_position < len(compressed):
            bit_buffer = (bit_buffer << 8) | compressed[compressed_position]
            available_bits += 8
            compressed_position += 1
        if available_bits == 0:
            raise HuffmanDecodeError(f"chunk {chunk_index}: truncated bit stream")
        # The dictionary's keys are short canonical codewords.  Accumulating
        # bits explicitly mirrors MEAnalyzer's MSB-first decoder and avoids
        # silently accepting a prefix that has no codeword.
        bit = (bit_buffer >> (available_bits - 1)) & 1
        current_bits += str(bit)
        available_bits -= 1
        if current_bits not in dictionary:
            if not any(key.startswith(current_bits) for key in dictionary):
                raise HuffmanDecodeError(
                    f"chunk {chunk_index}: no dictionary codeword for {current_bits!r}"
                )
            continue
        symbol = dictionary[current_bits]
        current_bits = ""
        if not symbol:
            raise HuffmanDecodeError(
                f"chunk {chunk_index}: dictionary contains an empty output symbol"
            )
        if len(output) + len(symbol) > expected_output_size:
            raise HuffmanDecodeError(
                f"chunk {chunk_index}: decoded output exceeds 0x{expected_output_size:x} bytes"
            )
        output.extend(symbol)
    if current_bits:
        # Padding is allowed only after the requested output is complete; a
        # partial codeword before completion is never accepted as data.
        if any(key.startswith(current_bits) for key in dictionary):
            pass
    return bytes(output)


def decompress_me11_huffman(
    module: bytes,
    *,
    stored_size: int,
    uncompressed_size: int,
    dictionary: ME11HuffmanDictionary,
) -> bytes:
    """Decode one bounded ME11 Huffman module using its real bytes."""

    if stored_size > len(module):
        raise HuffmanDecodeError(
            f"stored size 0x{stored_size:x} exceeds supplied module bytes 0x{len(module):x}"
        )
    module = module[:stored_size]
    encoded_offsets, header_size = _read_header(module, uncompressed_size, stored_size)
    output = bytearray()
    payload_size = stored_size - header_size
    for index, packed in enumerate(encoded_offsets):
        dictionary_type = packed >> 25
        start = packed & HUFFMAN_OFFSET_MASK
        end = (
            encoded_offsets[index + 1] & HUFFMAN_OFFSET_MASK
            if index + 1 < len(encoded_offsets)
            else payload_size
        )
        if end < start:
            raise HuffmanDecodeError(
                f"chunk {index}: compressed range reverses from 0x{start:x} to 0x{end:x}"
            )
        start += header_size
        end += header_size
        if end > stored_size:
            raise HuffmanDecodeError(f"chunk {index}: compressed range exceeds module")
        chunk = _decode_chunk(
            module[start:end],
            dictionary.tables[dictionary_type],
            min(CHUNK_SIZE, uncompressed_size - len(output)),
            chunk_index=index,
        )
        output.extend(chunk)
    if len(output) != uncompressed_size:
        raise HuffmanDecodeError(
            f"decoded output is 0x{len(output):x}, expected 0x{uncompressed_size:x} bytes"
        )
    return bytes(output)


__all__ = [
    "CHUNK_SIZE",
    "HuffmanDecodeError",
    "ME11HuffmanDictionary",
    "decompress_me11_huffman",
    "load_me11_dictionary",
]
