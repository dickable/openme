import unittest
from unittest import mock

try:
    import verify_lab
except ModuleNotFoundError:  # Supports ``python -m unittest tools.test_verify_lab``.
    from tools import verify_lab


class VerifyLabTests(unittest.TestCase):
    def test_report_imports_synthetic_modules_and_has_versions(self):
        report = verify_lab.run_verification()
        self.assertTrue(report.python_version)
        self.assertTrue(report.contract_version)
        for module_name in verify_lab.UNICORN_MODULES + verify_lab.QEMU_CONTRACT_MODULES:
            self.assertIn(
                verify_lab.CheckResult(f"import.{module_name}", "PASS", "importable"),
                report.checks,
            )
        self.assertTrue(any(check.name == "synthetic.qemu_contract" for check in report.checks))

    def test_unicorn_unavailable_fails_with_actionable_message(self):
        verify_lab._prepare_qemu_model_imports()
        runtime_module = __import__("csme.cpu.unicorn_runtime", fromlist=["*"])
        with mock.patch.object(runtime_module, "UNICORN_AVAILABLE", False), mock.patch.object(
            runtime_module,
            "UNICORN_IMPORT_ERROR",
            ImportError("simulated missing package"),
        ):
            report = verify_lab.run_verification()

        self.assertFalse(report.passed)
        unavailable = next(
            check for check in report.checks if check.name == "unicorn.available"
        )
        self.assertEqual(unavailable.status, "FAIL")
        self.assertIn("Unicorn unavailable", unavailable.detail)
        self.assertIn("optional 'unicorn' package", unavailable.detail)

    def test_json_report_is_serializable_without_file_output(self):
        report = verify_lab.run_verification()
        rendered = verify_lab.render_report(report, json_output=True)
        self.assertIn('"checks"', rendered)
        self.assertIn('"versions"', rendered)
        self.assertIn("synthetic-only", rendered)

    def test_main_returns_failure_status_for_failed_report(self):
        report = verify_lab.VerificationReport(
            passed=False,
            python_version="test",
            unicorn_version="unavailable",
            contract_version="framed-v1",
            checks=(verify_lab.CheckResult("unicorn.available", "FAIL", "Unicorn unavailable"),),
        )
        with mock.patch.object(verify_lab, "run_verification", return_value=report), mock.patch(
            "builtins.print"
        ) as printer:
            self.assertEqual(verify_lab.main([]), 1)
        printer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
