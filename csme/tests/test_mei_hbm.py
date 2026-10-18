import unittest

from csme.mei.mei_hbm import (
    BufferFullError,
    Interrupt,
    MEIHBMModel,
    MessageTooLargeError,
    NotReadyError,
    SideState,
)


class MEIHBMModelTests(unittest.TestCase):
    def test_reset_and_ready_handshake_gate_traffic(self) -> None:
        model = MEIHBMModel()
        self.assertEqual(model.host_state, SideState.RESET)
        self.assertEqual(model.me_state, SideState.RESET)
        with self.assertRaises(NotReadyError):
            model.host_submit(1, b"x")

        model.set_host_ready()
        with self.assertRaises(NotReadyError):
            model.host_submit(1, b"x")
        model.set_me_ready()
        self.assertTrue(model.ready)
        self.assertEqual(model.host_submit(1, b"x"), 0)

    def test_ring_wraps_and_preserves_fifo_order(self) -> None:
        model = MEIHBMModel(slot_count=2)
        model.set_ready()
        model.host_submit(1, b"a")
        model.host_submit(2, b"b")
        self.assertEqual(model.host_to_me_indices, (0, 0))
        report = model.me_service(limit=1)
        self.assertEqual(report.processed, 1)
        model.host_submit(3, b"c")
        self.assertEqual(
            [item.payload for item in model.pending_requests()], [b"b", b"c"]
        )

    def test_interrupts_are_set_by_new_data_and_acknowledgeable(self) -> None:
        model = MEIHBMModel()
        model.set_ready()
        model.host_submit(9, b"request")
        self.assertTrue(model.interrupts & Interrupt.ME_INPUT)
        model.me_service()
        self.assertTrue(model.interrupts & Interrupt.HOST_INPUT)
        model.host_poll_completion()
        self.assertTrue(model.interrupts & Interrupt.HOST_INPUT)
        model.ack_interrupts(Interrupt.ME_INPUT | Interrupt.HOST_INPUT)
        self.assertEqual(model.interrupts, Interrupt.NONE)

    def test_completion_matches_request(self) -> None:
        model = MEIHBMModel()
        model.set_ready()
        sequence = model.host_submit(0x20, b"hello")
        report = model.me_service()
        self.assertEqual(report.processed, 1)
        completion = model.host_poll_completion()
        self.assertEqual(completion.sequence, sequence)
        self.assertEqual(completion.opcode, 0x20)
        self.assertEqual(completion.status, 0)
        self.assertEqual(completion.payload, b"hello")

    def test_input_ring_full_is_bounded(self) -> None:
        model = MEIHBMModel(slot_count=2)
        model.set_ready()
        model.host_submit(1, b"a")
        model.host_submit(2, b"b")
        with self.assertRaises(BufferFullError):
            model.host_submit(3, b"c")

    def test_output_backpressure_does_not_drop_input(self) -> None:
        model = MEIHBMModel(slot_count=2)
        model.set_ready()
        model.host_submit(1, b"a")
        model.host_submit(2, b"b")
        first = model.me_service()
        self.assertEqual(first.processed, 2)
        model.host_submit(3, b"c")
        blocked = model.me_service()
        self.assertEqual(blocked.processed, 0)
        self.assertTrue(blocked.blocked_by_output_capacity)
        self.assertEqual([m.opcode for m in model.pending_requests()], [3])

        model.host_poll_completion()
        resumed = model.me_service()
        self.assertEqual(resumed.processed, 1)
        self.assertEqual(model.host_poll_completion().opcode, 2)
        self.assertEqual(model.host_poll_completion().opcode, 3)

    def test_payload_is_bounded_by_slot_size(self) -> None:
        model = MEIHBMModel(slot_size=16, header_size=4)
        model.set_ready()
        model.host_submit(1, b"123456789012")
        with self.assertRaises(MessageTooLargeError):
            model.host_submit(2, b"1234567890123")

    def test_reset_clears_rings_interrupts_and_sequence(self) -> None:
        model = MEIHBMModel()
        model.set_ready()
        model.host_submit(1, b"x")
        model.me_service()
        self.assertNotEqual(model.interrupts, Interrupt.NONE)
        model.reset()
        self.assertFalse(model.ready)
        self.assertEqual(model.host_to_me_count, 0)
        self.assertEqual(model.me_to_host_count, 0)
        self.assertEqual(model.interrupts, Interrupt.NONE)
        model.set_ready()
        self.assertEqual(model.host_submit(2, b"fresh"), 0)


if __name__ == "__main__":
    unittest.main()
