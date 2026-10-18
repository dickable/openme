"""Safe command and test-plan contract for the OpenME QEMU lab.

The contract is deliberately a data-only helper.  It constructs argument
tuples and an environment mapping; it never starts QEMU, reads a file, or
touches a host device.  Keeping the allowed arguments here makes it harder for
a runnable lab note to accidentally grow a firmware, network, or hardware
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass


# These identifiers belong to OpenME's synthetic test device.  They are not
# Intel identifiers and must remain visibly separate from a compatibility
# profile for any real platform.
OPENME_TEST_PCI_VENDOR_ID = 0x1234
OPENME_TEST_PCI_DEVICE_ID = 0x4D45
OPENME_TEST_PCI_ID = (
    f"{OPENME_TEST_PCI_VENDOR_ID:04x}:{OPENME_TEST_PCI_DEVICE_ID:04x}"
)

OPENME_QEMU_DEVICE = "openme-me"
OPENME_QEMU_MACHINE = "q35"
OPENME_QEMU_PCI_ADDRESS = "01.0"
OPENME_QTEST_PATH = "/openme/mmio-contract"


class QEMULabContractError(ValueError):
    """Raised when a lab command plan cannot be represented safely."""


def _require_nonempty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QEMULabContractError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class QTestInvocationPlan:
    """The executable, selector, and environment for the patched QTest.

    ``argv`` and ``environment`` are intentionally separate from shell
    syntax.  A caller may display or execute this plan in its own controlled
    environment, but this module does not provide an execution method.
    """

    qemu_binary: str = "qemu-system-x86_64"
    qtest_binary: str = "tests/qtest/openme-pci-test"
    test_path: str = OPENME_QTEST_PATH

    def __post_init__(self) -> None:
        _require_nonempty(self.qemu_binary, "qemu_binary")
        _require_nonempty(self.qtest_binary, "qtest_binary")
        if self.test_path != OPENME_QTEST_PATH:
            raise QEMULabContractError(
                f"test_path must be the project QTest {OPENME_QTEST_PATH!r}"
            )

    def argv(self) -> tuple[str, ...]:
        """Return the QTest executable arguments without starting a process."""

        return (self.qtest_binary, "--tap", "-p", self.test_path)

    def environment(self) -> dict[str, str]:
        """Return the only environment value needed by the QTest harness."""

        return {"QTEST_QEMU_BINARY": self.qemu_binary}


@dataclass(frozen=True)
class QEMULabContract:
    """Allowed direct-QEMU arguments and the matching QTest plan.

    The direct command is useful for inspecting the launch contract.  The
    normal regression path is the QTest plan, whose patched C test starts the
    same device with the same machine, address, and no-default-device policy.
    """

    qemu_binary: str = "qemu-system-x86_64"
    qtest_binary: str = "tests/qtest/openme-pci-test"

    def __post_init__(self) -> None:
        _require_nonempty(self.qemu_binary, "qemu_binary")
        _require_nonempty(self.qtest_binary, "qtest_binary")

    def qemu_argv(self) -> tuple[str, ...]:
        """Return a bounded, firmware-free, network-free QEMU argv tuple."""

        return (
            self.qemu_binary,
            "-machine",
            OPENME_QEMU_MACHINE,
            "-nodefaults",
            "-display",
            "none",
            "-net",
            "none",
            "-device",
            f"{OPENME_QEMU_DEVICE},addr={OPENME_QEMU_PCI_ADDRESS}",
        )

    def qtest_plan(self) -> QTestInvocationPlan:
        """Return the focused patched-QEMU test plan without executing it."""

        return QTestInvocationPlan(
            qemu_binary=self.qemu_binary,
            qtest_binary=self.qtest_binary,
        )


def build_qemu_argv(
    qemu_binary: str = "qemu-system-x86_64",
) -> tuple[str, ...]:
    """Build the safe direct-QEMU command shape without spawning QEMU."""

    return QEMULabContract(qemu_binary=qemu_binary).qemu_argv()


def build_qtest_plan(
    qemu_binary: str = "qemu-system-x86_64",
    qtest_binary: str = "tests/qtest/openme-pci-test",
) -> QTestInvocationPlan:
    """Build the focused QTest plan without spawning QEMU or QTest."""

    return QEMULabContract(
        qemu_binary=qemu_binary,
        qtest_binary=qtest_binary,
    ).qtest_plan()


# The mixed-case alias reads naturally for callers that use ``Qemu`` in local
# naming conventions while keeping the public class name explicit about QEMU.
QemuLabContract = QEMULabContract


__all__ = [
    "OPENME_QEMU_DEVICE",
    "OPENME_QEMU_MACHINE",
    "OPENME_QEMU_PCI_ADDRESS",
    "OPENME_QTEST_PATH",
    "OPENME_TEST_PCI_DEVICE_ID",
    "OPENME_TEST_PCI_ID",
    "OPENME_TEST_PCI_VENDOR_ID",
    "QEMULabContract",
    "QEMULabContractError",
    "QTestInvocationPlan",
    "QemuLabContract",
    "build_qemu_argv",
    "build_qtest_plan",
]
