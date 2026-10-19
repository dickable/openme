"""Bounded transport, independent snapshot verification, and commit regressions."""
import binascii
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.build_openme import ROOT, build
from tools.run_persist import (ACK, CHUNK, NOR_SIZE, commit_snapshot, exchange,
                               recvn, snapshot_count)


def fixture(count):
    data = bytearray(b"\xff" * NOR_SIZE)
    struct.pack_into("<HI", data, 0, 0x4653, 1)
    val = struct.pack("<I", count)
    crc = binascii.crc_hqx(b"\x00\x04\x00" + val, 0xffff)
    struct.pack_into("<HBBHH", data, 8, 0x4f46, 0, 255, 4, crc)
    data[16:20] = val
    return bytes(data)


class Stream:
    def __init__(self, data):
        self.data = data
        self.sent = []

    def recv(self, size):
        size = min(size, 3)  # deliberately split every header and payload
        block, self.data = self.data[:size], self.data[size:]
        return block

    def sendall(self, data):
        self.sent.append(data)

    def settimeout(self, timeout):
        assert timeout > 0


def wire_return(data, *, magic=b"OMO1", size=NOR_SIZE, crc=None, count=1):
    return (b"OMP1" + struct.pack("<I", NOR_SIZE) + ACK * (1 + NOR_SIZE // CHUNK) +
            struct.pack("<4s4I", magic, size, binascii.crc32(data) if crc is None else crc, count, 1) + data)


class PersistenceTests(unittest.TestCase):
    def tempdir(self):
        scratch = ROOT / "qemu-work/test-temp"
        scratch.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix="persist-test-", dir=scratch)

    def test_snapshot_count_reads_bytes_not_banner(self):
        self.assertEqual(snapshot_count(b"\xff" * NOR_SIZE), 0)
        self.assertEqual(snapshot_count(fixture(1)), 1)
        self.assertEqual(snapshot_count(fixture(2)), 2)
        damaged = bytearray(fixture(2))
        damaged[16] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC16"):
            snapshot_count(damaged)

    def test_invalid_snapshot_extent_and_records(self):
        for data in (b"", fixture(1)[:-1], fixture(1) + b"x", bytes(NOR_SIZE)):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                snapshot_count(data)
        damaged = bytearray(fixture(1))
        damaged[11] = 0  # only boot record is dead
        with self.assertRaisesRegex(ValueError, "no live"):
            snapshot_count(damaged)

    def test_exchange_handles_partial_stream_reads(self):
        data = fixture(1)
        stream = Stream(wire_return(data))
        actual, count, formatted = exchange(stream, b"\xff" * NOR_SIZE, time.monotonic() + 2)
        self.assertEqual((actual, count, formatted), (data, 1, 1))
        self.assertEqual(stream.sent[0][:8], b"OMI1" + struct.pack("<I", NOR_SIZE))
        self.assertEqual(b"".join(stream.sent[1:129]), b"\xff" * NOR_SIZE)
        self.assertEqual(stream.sent[129:], [ACK] * 129)
        self.assertFalse(stream.data)

    def test_exchange_rejects_bad_length_crc_magic_and_count(self):
        for fields in ({"size": 0xffffffff}, {"magic": b"oops"}, {"crc": 0}, {"count": 2}):
            stream = Stream(wire_return(fixture(1), **fields))
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                exchange(stream, b"\xff" * NOR_SIZE, time.monotonic() + 2)

    def test_closed_stream_timeout_and_unbounded_read(self):
        with self.assertRaises(RuntimeError):
            recvn(Stream(b"one"), 4, time.monotonic() + 2)
        with self.assertRaises(TimeoutError):
            recvn(Stream(b"one"), 3, time.monotonic() - 1)
        with self.assertRaises(ValueError):
            recvn(Stream(b"one"), 0xffffffff, time.monotonic() + 2)
        with self.assertRaises(ValueError):
            exchange(Stream(b""), bytes(4), time.monotonic() + 2)

    def test_atomic_commit_preserves_old_file_on_failure(self):
        with self.tempdir() as temp:
            path = Path(temp) / "flash.bin"
            before = b"\xff" * NOR_SIZE
            path.write_bytes(before)
            with patch("tools.run_persist.os.replace", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    commit_snapshot(path, before, fixture(1))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(temp).iterdir()), [path])
            commit_snapshot(path, before, fixture(1))
            self.assertEqual(path.read_bytes(), fixture(1))
            with self.assertRaisesRegex(ValueError, "changed"):
                commit_snapshot(path, before, fixture(2))
            self.assertEqual(path.read_bytes(), fixture(1))

    def test_unknown_profile_rejected_before_output_mutation(self):
        with self.tempdir() as temp:
            path = Path(temp) / "not-created"
            with self.assertRaises(ValueError):
                build(path, profile="typo")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
