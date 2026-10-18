import unittest

from csme.fake_devices.fake_me import Request, State
from csme.fake_devices.pci_shell import (
    CONTROL_ACK_IRQ,
    CONTROL_RESET,
    PCI_DEVICE_ID_OPENME_TEST,
    PCI_VENDOR_ID_OPENME_TEST,
    REG_CONTROL,
    REG_DOORBELL,
    REG_RX_LENGTH,
    REG_STATUS,
    REG_VERSION,
    STATUS_IRQ_PENDING,
    STATUS_READY,
    OpenMEPCIShell,
)


class PCIShellTests(unittest.TestCase):
    def test_uses_project_defined_identifiers(self):
        self.assertEqual(PCI_VENDOR_ID_OPENME_TEST, 0x1234)
        self.assertEqual(PCI_DEVICE_ID_OPENME_TEST, 0x4D45)

    def test_reset_and_doorbell_startup(self):
        shell = OpenMEPCIShell()
        shell.write(REG_CONTROL, CONTROL_RESET)
        self.assertTrue(shell.read(REG_STATUS) & STATUS_READY)
        shell.write(REG_DOORBELL, 2)
        self.assertTrue(shell.read(REG_STATUS) & STATUS_IRQ_PENDING)
        response = shell.pop_response()
        self.assertEqual(response.status, "ok")
        shell.write(REG_CONTROL, CONTROL_ACK_IRQ)
        self.assertFalse(shell.read(REG_STATUS) & STATUS_IRQ_PENDING)

    def test_response_length_and_reset_clear_queue(self):
        shell = OpenMEPCIShell()
        shell.write(REG_CONTROL, CONTROL_RESET)
        shell.submit(Request("START"))
        self.assertGreater(shell.read(REG_RX_LENGTH), 0)
        shell.write(REG_CONTROL, CONTROL_RESET)
        self.assertEqual(shell.read(REG_RX_LENGTH), 0)
        self.assertEqual(shell.model.state, State.READY)

    def test_full_model_request_can_cross_shell(self):
        shell = OpenMEPCIShell()
        shell.write(REG_CONTROL, CONTROL_RESET)
        shell.submit(Request("START"))
        shell.submit(Request("ENUMERATE"))
        self.assertEqual(shell.pop_response().status, "ok")
        self.assertIn(b"openme.echo", shell.pop_response().payload)


if __name__ == "__main__":
    unittest.main()

