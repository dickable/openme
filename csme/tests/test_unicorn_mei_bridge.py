import struct
import unittest

from csme.mei.mei_hbm import Interrupt, MessageTooLargeError
from csme.cpu.unicorn_runtime import UNICORN_AVAILABLE
from csme.mei.unicorn_mei_bridge import (
    BridgeError,
    UnicornMEIBridge,
)


@unittest.skipUnless(UNICORN_AVAILABLE, "optional Unicorn Python package is not installed")
class UnicornMEIBridgeTests(unittest.TestCase):
    def test_cpu_doorbell_produces_mei_completion(self):
        bridge = UnicornMEIBridge()
        result = bridge.submit(0x20, b"hello")

        self.assertEqual(result.completion.sequence, 0)
        self.assertEqual(result.completion.opcode, 0x20)
        self.assertEqual(result.completion.status, 0)
        self.assertEqual(result.completion.payload, b"hello")
        self.assertEqual(struct.unpack("<III", bridge.response_bytes()[:12]), (0, 0x20, 0))
        self.assertEqual(bridge.response_bytes()[12:], b"hello")
        self.assertEqual(bridge.model.interrupts, Interrupt.NONE)
        self.assertEqual(bridge.model.host_to_me_count, 0)
        self.assertEqual(bridge.model.me_to_host_count, 0)
        self.assertIn("host_submit:0:32", result.events)
        self.assertIn("me_complete:0:0", result.events)

    def test_repeated_transactions_are_deterministic(self):
        bridge = UnicornMEIBridge()
        first = bridge.submit(7, b"same")
        first_registers = bridge.runtime.registers()
        second = bridge.submit(7, b"same")

        self.assertEqual(first, second)
        self.assertEqual(first_registers, bridge.runtime.registers())
        self.assertEqual(bridge.response_bytes()[12:], b"same")

    def test_invalid_opcode_is_rejected_before_cpu_run(self):
        bridge = UnicornMEIBridge()
        with self.assertRaises(BridgeError):
            bridge.submit(-1, b"x")

    def test_payload_limit_is_inherited_from_transport(self):
        bridge = UnicornMEIBridge()
        with self.assertRaises(MessageTooLargeError):
            bridge.submit(1, b"x" * (bridge.model.max_payload + 1))


if __name__ == "__main__":
    unittest.main()
