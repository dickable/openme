"""Run a bounded, synthetic-only verification of the local OpenME lab.

This utility intentionally does not inspect firmware, start QEMU, access
hardware, use the network, or write files.  The optional Unicorn dependency
is required for the CPU and bridge checks; the QEMU-facing checks use only the
project-defined Python contracts.
"""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


UTILITY_VERSION = "1"
MAX_SYNTHETIC_INSTRUCTIONS = 32
MAX_SYNTHETIC_PAYLOAD = 32

UNICORN_MODULES = ("csme.cpu.unicorn_runtime", "csme.mei.unicorn_mei_bridge")
QEMU_CONTRACT_MODULES = (
    "csme.fake_devices.fake_me",
    "csme.fake_devices.framed_transport",
    "csme.runtime.me_runtime_contract",
    "csme.mei.mei_hbm",
    "csme.fake_devices.pci_shell",
    "csme.fake_devices.qemu_lab_contract",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class VerificationReport:
    passed: bool
    python_version: str
    unicorn_version: str
    contract_version: str
    checks: tuple[CheckResult, ...]

    @property
    def unicorn_available(self) -> bool:
        return any(
            check.name == "unicorn.available" and check.status == "PASS"
            for check in self.checks
        )


def _prepare_qemu_model_imports() -> None:
    """Make the repository's CSME package importable."""

    model_path = str(Path(__file__).resolve().parents[1])
    if model_path not in sys.path:
        sys.path.insert(0, model_path)


def _load_modules(module_names: Iterable[str]) -> tuple[dict[str, Any], list[CheckResult]]:
    modules: dict[str, Any] = {}
    checks: list[CheckResult] = []
    for module_name in module_names:
        try:
            modules[module_name.rsplit(".", 1)[-1]] = importlib.import_module(module_name)
        except Exception as exc:  # Import failures should be visible per module.
            checks.append(
                CheckResult(
                    f"import.{module_name}",
                    "FAIL",
                    f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            checks.append(CheckResult(f"import.{module_name}", "PASS", "importable"))
    return modules, checks


def _unicorn_version() -> str:
    try:
        package = importlib.import_module("unicorn")
    except Exception as exc:
        return f"unavailable ({type(exc).__name__}: {exc})"
    return str(getattr(package, "__version__", "installed; version not exposed"))


def _run_unicorn_checks(runtime_module: Any, bridge_module: Any) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if not getattr(runtime_module, "UNICORN_AVAILABLE", False):
        error = getattr(runtime_module, "UNICORN_IMPORT_ERROR", None)
        detail = str(error) if error else "the optional package was not found"
        checks.append(
            CheckResult(
                "unicorn.available",
                "FAIL",
                "Unicorn unavailable: "
                f"{detail}. Install the optional 'unicorn' package to run this check.",
            )
        )
        return checks

    checks.append(CheckResult("unicorn.available", "PASS", "optional package is importable"))

    try:
        runtime_class = runtime_module.UnicornRuntime
        runtime = runtime_class()
        runtime.load_synthetic_code(runtime_module.synthetic_sum_program())
        runtime.run(count=MAX_SYNTHETIC_INSTRUCTIONS)
        registers = runtime.registers()
        if registers["eax"] != 0x2468ACF0:
            raise AssertionError(f"unexpected synthetic EAX: 0x{registers['eax']:x}")
        checks.append(
            CheckResult(
                "synthetic.unicorn_runtime",
                "PASS",
                f"sum program completed within {MAX_SYNTHETIC_INSTRUCTIONS} instructions",
            )
        )
    except Exception as exc:
        checks.append(
            CheckResult(
                "synthetic.unicorn_runtime",
                "FAIL",
                f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        base_runtime = runtime_module.UnicornRuntime

        class BoundedRuntime(base_runtime):
            def run(self, start=None, stop=0, count=0):
                bounded_count = min(
                    count or MAX_SYNTHETIC_INSTRUCTIONS,
                    MAX_SYNTHETIC_INSTRUCTIONS,
                )
                return super().run(start=start, stop=stop, count=bounded_count)

        bridge = bridge_module.UnicornMEIBridge(runtime=BoundedRuntime())
        result = bridge.submit(0x20, b"lab")
        if result.completion.payload != b"lab" or result.completion.status != 0:
            raise AssertionError("synthetic bridge completion was not an echo success")
        checks.append(
            CheckResult(
                "synthetic.unicorn_bridge",
                "PASS",
                "bounded mailbox transaction completed with a synthetic payload",
            )
        )
    except Exception as exc:
        checks.append(
            CheckResult(
                "synthetic.unicorn_bridge",
                "FAIL",
                f"{type(exc).__name__}: {exc}",
            )
        )
    return checks


def _run_qemu_contract_check(modules: dict[str, Any]) -> CheckResult:
    try:
        pci_shell = modules["pci_shell"]
        shell = pci_shell.OpenMEPCIShell()
        shell.write(pci_shell.REG_CONTROL, pci_shell.CONTROL_RESET)
        shell.write(pci_shell.REG_DOORBELL, 2)
        response = shell.pop_response()
        if response.status != "ok":
            raise AssertionError(f"PCI contract START status: {response.status}")
        pci_version = shell.read(pci_shell.REG_VERSION)

        framed = modules["framed_transport"]
        transport = framed.FramedTransport()
        for sequence, opcode, client in (
            (1, framed.Opcode.RESET, ""),
            (2, framed.Opcode.START, ""),
            (3, framed.Opcode.ENUMERATE, ""),
            (4, framed.Opcode.CONNECT, "openme.echo"),
        ):
            request = framed.Frame(opcode, sequence).encode()
            framed.decode_frame(transport.handle(request, client=client))
        data_request = framed.Frame(framed.Opcode.DATA, 5, b"lab").encode()
        data_response = framed.decode_frame(
            transport.handle(data_request, client="openme.echo")
        )
        if data_response.status != framed.Status.OK or data_response.payload != b"lab":
            raise AssertionError("framed contract did not echo the bounded payload")

        qemu_lab = modules["qemu_lab_contract"]
        qemu_argv = qemu_lab.build_qemu_argv("synthetic-qemu")
        if "-bios" in qemu_argv or "-drive" in qemu_argv or "-netdev" in qemu_argv:
            raise AssertionError("QEMU contract contains a forbidden external input")
        qtest_plan = qemu_lab.build_qtest_plan("synthetic-qemu", "synthetic-qtest")
        if qtest_plan.environment()["QTEST_QEMU_BINARY"] != "synthetic-qemu":
            raise AssertionError("QTest plan did not preserve the synthetic executable")

        contract = modules["me_runtime_contract"]
        memory = contract.DeterministicMemory()
        memory.map_region(contract.MemoryRegion("ram", 0x1000, 16, False))
        memory.write(0x1000, b"lab")
        if memory.read(0x1000, 3) != b"lab":
            raise AssertionError("runtime contract memory round-trip failed")
    except KeyError as exc:
        return CheckResult("synthetic.qemu_contract", "FAIL", f"missing module: {exc}")
    except Exception as exc:
        return CheckResult("synthetic.qemu_contract", "FAIL", f"{type(exc).__name__}: {exc}")
    return CheckResult(
        "synthetic.qemu_contract",
        "PASS",
        f"PCI/MMIO v0x{pci_version:08x}; framed transport v{framed.VERSION}; "
        "data-only QEMU plan; bounded payload",
    )


def run_verification() -> VerificationReport:
    """Run all local checks and return a deterministic report object."""

    _prepare_qemu_model_imports()
    modules, checks = _load_modules(UNICORN_MODULES + QEMU_CONTRACT_MODULES)

    runtime_module = modules.get("unicorn_runtime")
    bridge_module = modules.get("unicorn_mei_bridge")
    if runtime_module is None or bridge_module is None:
        checks.append(
            CheckResult(
                "unicorn.available",
                "FAIL",
                "Unicorn checks cannot run because the bridge/runtime import failed.",
            )
        )
        unicorn_version = "unavailable"
    else:
        checks.extend(_run_unicorn_checks(runtime_module, bridge_module))
        unicorn_version = _unicorn_version()

    if all(name.rsplit(".", 1)[-1] in modules for name in QEMU_CONTRACT_MODULES):
        checks.append(_run_qemu_contract_check(modules))
        contract_version = f"framed-v{modules['framed_transport'].VERSION}"
    else:
        checks.append(
            CheckResult(
                "synthetic.qemu_contract",
                "FAIL",
                "QEMU contract checks cannot run because a contract module failed to import.",
            )
        )
        contract_version = "unavailable"

    return VerificationReport(
        passed=all(check.status == "PASS" for check in checks),
        python_version=platform.python_version(),
        unicorn_version=unicorn_version,
        contract_version=contract_version,
        checks=tuple(checks),
    )


def _report_dict(report: VerificationReport) -> dict[str, Any]:
    return {
        "utility_version": UTILITY_VERSION,
        "scope": "local synthetic-only; no firmware, network, hardware, or QEMU launch",
        "passed": report.passed,
        "versions": {
            "python": report.python_version,
            "unicorn": report.unicorn_version,
            "qemu_contract": report.contract_version,
        },
        "checks": [asdict(check) for check in report.checks],
    }


def render_report(report: VerificationReport, *, json_output: bool = False) -> str:
    if json_output:
        return json.dumps(_report_dict(report), indent=2, sort_keys=True)

    lines = [
        f"OpenME local lab verification v{UTILITY_VERSION}",
        "scope: synthetic-only; no firmware, network, hardware, or QEMU launch",
        f"versions: Python {report.python_version}; Unicorn {report.unicorn_version}; "
        f"QEMU contract {report.contract_version}",
        "checks:",
    ]
    lines.extend(f"  {check.status}: {check.name} - {check.detail}" for check in report.checks)
    lines.append(f"status: {'PASS' if report.passed else 'FAIL'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit the report as JSON",
    )
    args = parser.parse_args(argv)
    report = run_verification()
    print(render_report(report, json_output=args.json_output))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
