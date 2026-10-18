import unittest

from csme.fake_devices.fake_me import FakeME
from csme.fake_devices.framed_transport import (
    ERROR_FLAG,
    Opcode,
    Frame,
    FrameError,
    FramedTransport,
    QueuedFramedTransport,
    Status,
    decode_frame,
)


def request(opcode: Opcode, sequence: int, payload: bytes = b"") -> bytes:
    return Frame(opcode=opcode, sequence=sequence, payload=payload).encode()


class FramedTransportTests(unittest.TestCase):
    def test_wire_round_trip(self):
        original = Frame(Opcode.DATA, 4, b"hello-openme")
        self.assertEqual(decode_frame(original.encode()), original)

    def test_start_and_echo(self):
        transport = FramedTransport(FakeME())
        self.assertEqual(decode_frame(transport.handle(request(Opcode.RESET, 1))).status, Status.OK)
        self.assertEqual(decode_frame(transport.handle(request(Opcode.START, 2))).status, Status.OK)
        transport.handle(request(Opcode.ENUMERATE, 3))
        transport.handle(request(Opcode.CONNECT, 4), client="openme.echo")
        response = decode_frame(transport.handle(
            request(Opcode.DATA, 5, b"hello-openme"), client="openme.echo"
        ))
        self.assertEqual(response.status, Status.OK)
        self.assertEqual(response.payload, b"hello-openme")
        self.assertTrue(response.flags & 1)

    def test_unknown_opcode_is_framed_error(self):
        response = decode_frame(FramedTransport().handle(request(0x7F, 7)))
        self.assertEqual(response.status, Status.UNKNOWN_OPCODE)
        self.assertEqual(response.flags, 1 | ERROR_FLAG)
        self.assertEqual(response.payload, b"")

    def test_malformed_complete_frame_gets_error_response(self):
        malformed = bytearray(request(Opcode.START, 8))
        malformed[12:14] = (1).to_bytes(2, "little")
        response = decode_frame(FramedTransport().handle(bytes(malformed)))
        self.assertEqual(response.status, Status.BAD_LENGTH)

    def test_short_frame_is_rejected_before_response(self):
        with self.assertRaises(FrameError):
            FramedTransport().handle(b"too-short")

    def test_queued_service_and_fifo_response(self):
        transport = QueuedFramedTransport(FakeME())
        self.assertEqual(transport.submit(request(Opcode.RESET, 1)), Status.OK)
        self.assertEqual(decode_frame(transport.service()).status, Status.OK)
        self.assertEqual(transport.submit(request(Opcode.START, 2)), Status.OK)
        self.assertEqual(decode_frame(transport.service()).status, Status.OK)
        self.assertEqual(decode_frame(transport.pop_response()).sequence, 1)
        self.assertEqual(decode_frame(transport.pop_response()).sequence, 2)
        self.assertIsNone(transport.pop_response())

    def test_queue_full_is_atomic(self):
        transport = QueuedFramedTransport(FakeME())
        for sequence in range(1, 9):
            self.assertEqual(transport.submit(request(Opcode.RESET, sequence)), Status.OK)
        self.assertEqual(transport.submit(request(Opcode.RESET, 9)), Status.QUEUE_FULL)
        self.assertEqual(transport.overflow_count, 1)
        self.assertEqual(len(transport.request_queue), 8)

    def test_complete_malformed_frame_is_processed(self):
        transport = QueuedFramedTransport(FakeME())
        malformed = bytearray(request(Opcode.START, 10))
        malformed[6:8] = (1).to_bytes(2, "little")
        self.assertEqual(transport.submit(bytes(malformed)), Status.OK)
        response = decode_frame(transport.service())
        self.assertEqual(response.status, Status.BAD_LENGTH)

    def test_incomplete_declared_payload_is_rejected(self):
        transport = QueuedFramedTransport(FakeME())
        incomplete = bytearray(request(Opcode.START, 11))
        incomplete[12:14] = (1).to_bytes(2, "little")
        self.assertEqual(transport.submit(bytes(incomplete)), Status.BAD_LENGTH)
        self.assertIsNone(transport.service())


if __name__ == "__main__":
    unittest.main()
