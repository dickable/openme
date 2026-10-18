"""User-facing, software-only console for the OpenME research model.

The model implementation lives in ``csme/runtime/research_console.py``.  This
file is deliberately only a presentation and input boundary: it does not
start QEMU, load firmware, inspect a firmware image, access hardware, or use
the network.
"""

from __future__ import annotations

import argparse
import importlib
import shlex
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, TextIO


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT
BACKEND_MODULE = "csme.runtime.research_console"
DEFAULT_PROMPT = "openme> "

CLI_HELP_TEXT = "CLI commands:\n  quit, exit              leave the console"

COMMANDS = {
    "help",
    "state",
    "reset",
    "heci-status",
    "boot",
    "dir",
    "cat",
    "suspend",
    "resume",
    "send",
    "trace",
    "quit",
    "exit",
}


class ConsoleError(Exception):
    """A user-facing console error."""


class BackendUnavailable(ConsoleError):
    """Raised when the research-console backend cannot be loaded."""


def _load_backend_module() -> Any:
    """Load the local research backend without importing any other runtime."""

    model_path = str(MODEL_PATH)
    if model_path not in sys.path:
        sys.path.insert(0, model_path)
    try:
        return importlib.import_module(BACKEND_MODULE)
    except (ImportError, OSError) as exc:
        raise BackendUnavailable(
            "csme/runtime/research_console.py is required; "
            f"the software-only backend could not be loaded ({exc})"
        ) from exc


def _make_backend(module: Any) -> Any:
    """Construct the backend using its small, intentionally local API.

    ``ResearchConsole`` is the preferred name.  ``create_console`` is also
    accepted so the backend can expose a factory without making the CLI know
    about its implementation details.
    """

    constructor = getattr(module, "ResearchConsole", None)
    if constructor is None:
        constructor = getattr(module, "create_console", None)
    if constructor is None or not callable(constructor):
        raise BackendUnavailable(
            "csme/runtime/research_console.py must expose ResearchConsole "
            "or create_console"
        )
    try:
        return constructor()
    except Exception as exc:  # backend errors must become readable CLI errors
        raise BackendUnavailable(f"could not initialize research console: {exc}") from exc


def load_backend() -> Any:
    """Load and initialize the local research-console backend."""

    return _make_backend(_load_backend_module())


def _call_backend(backend: Any, command: str) -> Any:
    """Send one complete command line to the backend.

    The backend's public operation is ``execute(line)``.  The two aliases are
    accepted for compatibility with small research-only implementations while
    preserving a single command-line boundary for deterministic scripts.
    """

    for name in ("execute", "run_command", "handle_command"):
        operation = getattr(backend, name, None)
        if callable(operation):
            return operation(command)
    raise ConsoleError(
        "research console backend must expose execute(line), "
        "run_command(line), or handle_command(line)"
    )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + value.hex()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def format_result(result: Any) -> str:
    """Format common backend results into stable, readable one-line output."""

    result = _jsonable(result)
    if result is None:
        return "OK"
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        fields = [f"{key}={result[key]}" for key in sorted(result)]
        return "OK" if not fields else "OK: " + " ".join(fields)
    if isinstance(result, list):
        return "OK: " + "; ".join(str(item) for item in result)
    return f"OK: {result}"


def _validate_line(line: str) -> tuple[str, list[str]]:
    try:
        tokens = shlex.split(line, posix=True)
    except ValueError as exc:
        raise ConsoleError(f"invalid command syntax: {exc}") from exc
    if not tokens:
        return "", []
    command = tokens[0].lower()
    if command not in COMMANDS:
        raise ConsoleError(f"invalid command {tokens[0]!r}; type 'help' for commands")
    if command in {"help", "quit", "exit"} and tokens[1:]:
        raise ConsoleError(f"{command} does not accept arguments")
    return command, tokens[1:]


def _canonical_command(command: str, args: list[str]) -> str:
    """Return a normalized line while preserving arguments as shell words."""

    if command in {"help", "quit", "exit"}:
        return command
    if command == "send" and len(args) >= 2:
        # Keep the payload as one argument after parsing, even when it has
        # spaces.  shlex.join is available on all supported Python versions.
        return shlex.join([command, args[0], " ".join(args[1:])])
    return shlex.join([command, *args])


class ConsoleApp:
    """Run commands against an already-created research-console backend."""

    def __init__(
        self,
        backend: Any,
        *,
        output: TextIO | None = None,
        error: TextIO | None = None,
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        self.backend = backend
        self.output = output or sys.stdout
        self.error = error or sys.stderr
        self.prompt = prompt
        self.should_exit = False
        self.had_error = False

    def write_error(self, message: str) -> None:
        self.had_error = True
        print(f"error: {message}", file=self.error)

    def execute_line(self, line: str) -> bool:
        """Execute one line and return whether the session should continue."""

        try:
            command, args = _validate_line(line)
            if not command:
                return True
            if command == "help":
                backend_help = format_result(_call_backend(self.backend, "help"))
                print(f"{backend_help}\n{CLI_HELP_TEXT}", file=self.output)
                return True
            if command in {"quit", "exit"}:
                print("bye", file=self.output)
                self.should_exit = True
                return False
            normalized = _canonical_command(command, args)
            print(format_result(_call_backend(self.backend, normalized)), file=self.output)
        except (ConsoleError, ValueError, TypeError, RuntimeError) as exc:
            self.write_error(str(exc))
        return True

    def run(self, lines: Iterable[str], *, interactive: bool = False) -> int:
        if interactive:
            iterator = iter(lines)
            while not self.should_exit:
                print(self.prompt, end="", file=self.output, flush=True)
                try:
                    raw_line = next(iterator)
                except StopIteration:
                    break
                if not self.execute_line(raw_line.rstrip("\r\n")):
                    break
            return 1 if self.had_error else 0

        for raw_line in lines:
            if self.should_exit:
                break
            if not self.execute_line(raw_line.rstrip("\r\n")):
                break
        return 1 if self.had_error else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interact with the software-only OpenME research console."
    )
    parser.add_argument(
        "--script",
        metavar="PATH",
        help="read deterministic commands from PATH; use '-' for stdin",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    backend: Any | None = None,
    input_stream: TextIO | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
) -> int:
    """CLI entry point; dependency injection keeps tests hardware-free."""

    args = _parser().parse_args(argv)
    input_stream = input_stream or sys.stdin
    output = output or sys.stdout
    error = error or sys.stderr

    try:
        backend = backend if backend is not None else load_backend()
        app = ConsoleApp(backend, output=output, error=error)
        if args.script and args.script != "-":
            try:
                with Path(args.script).open("r", encoding="utf-8", newline=None) as script:
                    return app.run(script)
            except OSError as exc:
                print(f"error: cannot read script {args.script!r}: {exc}", file=error)
                return 2
        is_tty = getattr(input_stream, "isatty", lambda: False)()
        return app.run(input_stream, interactive=args.script is None and is_tty)
    except BackendUnavailable as exc:
        print(f"error: {exc}", file=error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
