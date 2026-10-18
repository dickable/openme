import unittest
from pathlib import Path

from csme.runtime.huffman import (
    CHUNK_SIZE,
    HuffmanDecodeError,
    ME11HuffmanDictionary,
    decompress_me11_huffman,
)


class HuffmanTests(unittest.TestCase):
    def test_me11_chunk_table_and_msb_stream_decode(self):
        dictionary = ME11HuffmanDictionary(
            path=Path("fixture-Huffman.dat"),
            sha256="fixture",
            tables={
                0x20: {"0": b"A", "1": b"B"},
                0x60: {"0": b"A", "1": b"B"},
            },
        )
        compressed = bytes((0x00,)) * (CHUNK_SIZE // 8)
        module = (0x40000000).to_bytes(4, "little") + compressed
        decoded = decompress_me11_huffman(
            module,
            stored_size=len(module),
            uncompressed_size=CHUNK_SIZE,
            dictionary=dictionary,
        )
        self.assertEqual(decoded, b"A" * CHUNK_SIZE)

    def test_unknown_dictionary_type_is_hard_failure(self):
        dictionary = ME11HuffmanDictionary(
            path=Path("fixture-Huffman.dat"),
            sha256="fixture",
            tables={0x20: {"0": b"A"}, 0x60: {"0": b"A"}},
        )
        module = (0x01000000).to_bytes(4, "little") + b"\x00"
        with self.assertRaises(HuffmanDecodeError):
            decompress_me11_huffman(
                module,
                stored_size=len(module),
                uncompressed_size=CHUNK_SIZE,
                dictionary=dictionary,
            )


if __name__ == "__main__":
    unittest.main()
