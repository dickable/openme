import unittest

from csme.fake_devices.qemu_lab_contract import (
    OPENME_QEMU_DEVICE,
    OPENME_QEMU_MACHINE,
    OPENME_QEMU_PCI_ADDRESS,
    OPENME_QTEST_PATH,
    OPENME_TEST_PCI_DEVICE_ID,
    OPENME_TEST_PCI_VENDOR_ID,
    QEMULabContract,
    QEMULabContractError,
    QTestInvocationPlan,
    build_qemu_argv,
    build_qtest_plan,
)


class QEMULabContractTests(unittest.TestCase):
    def test_identifiers_are_explicit_project_test_values(self):
        self.assertEqual(OPENME_TEST_PCI_VENDOR_ID, 0x1234)
        self.assertEqual(OPENME_TEST_PCI_DEVICE_ID, 0x4D45)
        self.assertNotEqual(OPENME_TEST_PCI_VENDOR_ID, 0x8086)

    def test_direct_command_is_fixed_and_has_no_network_or_firmware_inputs(self):
        argv = build_qemu_argv("build/qemu-system-x86_64")

        self.assertEqual(
            argv,
            (
                "build/qemu-system-x86_64",
                "-machine",
                OPENME_QEMU_MACHINE,
                "-nodefaults",
                "-display",
                "none",
                "-net",
                "none",
                "-device",
                f"{OPENME_QEMU_DEVICE},addr={OPENME_QEMU_PCI_ADDRESS}",
            ),
        )
        self.assertNotIn("-bios", argv)
        self.assertNotIn("-drive", argv)
        self.assertNotIn("-kernel", argv)
        self.assertNotIn("-nic", argv)
        self.assertNotIn("-netdev", argv)

    def test_qtest_plan_selects_only_the_openme_contract_test(self):
        plan = build_qtest_plan(
            qemu_binary="build/qemu-system-x86_64",
            qtest_binary="build/tests/qtest/openme-pci-test",
        )

        self.assertEqual(
            plan.argv(),
            (
                "build/tests/qtest/openme-pci-test",
                "--tap",
                "-p",
                OPENME_QTEST_PATH,
            ),
        )
        self.assertEqual(
            plan.environment(),
            {"QTEST_QEMU_BINARY": "build/qemu-system-x86_64"},
        )

    def test_contract_rejects_empty_executable_names(self):
        with self.assertRaises(QEMULabContractError):
            QEMULabContract(qemu_binary="")
        with self.assertRaises(QEMULabContractError):
            build_qtest_plan(qtest_binary=" ")

    def test_contract_rejects_a_different_qtest_selector(self):
        with self.assertRaises(QEMULabContractError):
            QTestInvocationPlan(test_path="/other/test")


if __name__ == "__main__":
    unittest.main()
