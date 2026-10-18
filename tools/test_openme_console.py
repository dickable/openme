import io
import tempfile
import unittest
from pathlib import Path

try:
    from tools.openme_console import ConsoleApp, format_result, main
except ModuleNotFoundError:  # supports running this test from the tools directory
    from openme_console import ConsoleApp, format_result, main


class FakeResearchConsole:
    """Small in-memory backend double; it cannot access external resources."""

    def __init__(self):
        self.commands = []

    def execute(self, line):
        self.commands.append(line)
        if line == "bad-backend":
            raise ValueError("backend rejected command")
        return {"command": line, "status": "ok"}


class OpenMEConsoleTests(unittest.TestCase):
    def test_format_result_is_readable_and_handles_bytes(self):
        self.assertEqual(
            format_result({"status": "ok", "payload": b"hello"}),
            "OK: payload=hello status=ok",
        )
        self.assertEqual(format_result(None), "OK")

    def test_help_is_forwarded_to_the_research_backend(self):
        backend = FakeResearchConsole()
        output = io.StringIO()
        app = ConsoleApp(backend, output=output, error=io.StringIO())

        self.assertTrue(app.execute_line("help"))
        self.assertIn("command=help", output.getvalue())
        self.assertEqual(backend.commands, ["help"])

    def test_commands_are_normalized_and_payload_spaces_are_preserved(self):
        backend = FakeResearchConsole()
        output = io.StringIO()
        app = ConsoleApp(backend, output=output, error=io.StringIO())

        app.execute_line("HECI-STATUS")
        app.execute_line('send 0x2a "hello openme"')

        self.assertEqual(
            backend.commands,
            ["heci-status", "send 0x2a 'hello openme'"],
        )
        self.assertIn("status=ok", output.getvalue())

    def test_invalid_commands_are_reported_and_session_continues(self):
        backend = FakeResearchConsole()
        output = io.StringIO()
        error = io.StringIO()
        app = ConsoleApp(backend, output=output, error=error)

        self.assertTrue(app.execute_line("not-a-command"))
        self.assertTrue(app.execute_line("heci-status"))

        self.assertIn("invalid command", error.getvalue())
        self.assertEqual(backend.commands, ["heci-status"])
        self.assertEqual(app.run([], interactive=False), 1)

    def test_backend_errors_are_reported_without_crashing(self):
        class ErrorBackend:
            def execute(self, line):
                raise ValueError("invalid model state")

        error = io.StringIO()
        app = ConsoleApp(ErrorBackend(), output=io.StringIO(), error=error)

        self.assertTrue(app.execute_line("reset"))
        self.assertIn("invalid model state", error.getvalue())

    def test_interactive_mode_prints_prompt_before_each_input(self):
        backend = FakeResearchConsole()
        output = io.StringIO()
        app = ConsoleApp(backend, output=output, error=io.StringIO())

        self.assertEqual(app.run(io.StringIO("heci-status\nexit\n"), interactive=True), 0)
        self.assertTrue(output.getvalue().startswith("openme> OK:"))
        self.assertEqual(output.getvalue().count("openme> "), 2)

    def test_local_commands_reject_extra_arguments(self):
        error = io.StringIO()
        app = ConsoleApp(FakeResearchConsole(), output=io.StringIO(), error=error)

        self.assertTrue(app.execute_line("help now"))
        self.assertIn("help does not accept arguments", error.getvalue())

    def test_script_mode_is_deterministic_and_stops_at_exit(self):
        backend = FakeResearchConsole()
        output = io.StringIO()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            script = Path(directory) / "commands.txt"
            script.write_text("reset\nexit\nstate\n", encoding="utf-8")
            result = main(
                ["--script", str(script)],
                backend=backend,
                output=output,
                error=io.StringIO(),
            )

        self.assertEqual(result, 0)
        self.assertEqual(backend.commands, ["reset"])
        self.assertIn("bye", output.getvalue())

    def test_script_invalid_command_returns_error_but_continues(self):
        backend = FakeResearchConsole()
        output = io.StringIO()
        error = io.StringIO()
        result = main(
            ["--script", "-"],
            backend=backend,
            input_stream=io.StringIO("bad\nheci-status\n"),
            output=output,
            error=error,
        )

        self.assertEqual(result, 1)
        self.assertEqual(backend.commands, ["heci-status"])
        self.assertIn("invalid command", error.getvalue())


if __name__ == "__main__":
    unittest.main()
