"""Deterministic, synthetic research-console façade.

The console is a small in-memory wrapper around :class:`UnicornMEIBridge`
and :class:`MEIHBMModel`.  It exposes the model as Python methods and as a
bounded command dispatcher for repeatable experiments.  The console accepts
only caller-provided opcode and UTF-8 payload values; it has no loader,
device, process, or network integration.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from ..mei.mei_hbm import MEIError, MEIHBMModel
from .me_boot_runtime import BootRuntimeError, SyntheticMERuntime
from ..mei.unicorn_mei_bridge import BridgeError, BridgeResult, UnicornMEIBridge


class ResearchConsoleError(ValueError):
    """Raised when a console command or argument is invalid."""


HELP_TEXT = "\n".join(
    (
        "commands:",
        "  help",
        "  state",
        "  reset",
        "  heci-status",
        "  boot",
        "  dir [path]",
        "  cat <path>",
        "  suspend",
        "  resume",
        "  send <opcode> <utf8 payload>",
        "  trace",
    )
)


class ResearchConsole:
    """Expose one deterministic synthetic transport session.

    ``bridge`` can be supplied by tests or a caller that already owns a
    :class:`UnicornMEIBridge`.  When it is omitted, the bridge is created
    lazily on the first ``send`` so read-only commands remain usable without
    the optional CPU runtime.
    """

    def __init__(
        self,
        bridge: UnicornMEIBridge | None = None,
        model: MEIHBMModel | None = None,
    ) -> None:
        if bridge is not None and model is not None and bridge.model is not model:
            raise ResearchConsoleError("bridge and model must refer to the same model")

        self._bridge = bridge
        self.model = bridge.model if bridge is not None else (model or MEIHBMModel())
        self.runtime = SyntheticMERuntime()
        if bridge is None:
            self.model.reset()
            self.model.set_ready()

        self._last_completion: dict[str, Any] | None = None
        self._last_trace: tuple[str, ...] = tuple(
            bridge.events if bridge is not None else ()
        )

    @property
    def bridge(self) -> UnicornMEIBridge:
        """Return the wrapped bridge, constructing it only when needed."""

        if self._bridge is None:
            self._bridge = UnicornMEIBridge(model=self.model)
        return self._bridge

    def help(self) -> str:
        """Return the stable command help text."""

        return HELP_TEXT

    def state(self) -> dict[str, Any]:
        """Return a JSON-compatible snapshot of the synthetic session."""

        return {
            "boot": self.runtime.state(),
            "host_state": self.model.host_state.value,
            "me_state": self.model.me_state.value,
            "ready": self.model.ready,
            "interrupts": int(self.model.interrupts),
            "pending_requests": self.model.host_to_me_count,
            "pending_completions": self.model.me_to_host_count,
            "last_completion": (
                dict(self._last_completion) if self._last_completion is not None else None
            ),
        }

    def reset(self) -> dict[str, Any]:
        """Reset the model and bridge to a ready, empty baseline."""

        self.model.reset()
        self.model.set_ready()
        self.runtime.reset()
        if self._bridge is not None:
            self._bridge.runtime.reset()
            self._bridge.events.clear()
            self._bridge._completion = None
        self._last_completion = None
        self._last_trace = ("reset",)
        return self.state()

    def boot(self) -> dict[str, object]:
        """Boot the synthetic runtime environment."""

        return self.runtime.boot()

    def list_dir(self, path: str = "/") -> tuple[str, ...]:
        try:
            return self.runtime.list_dir(path)
        except BootRuntimeError as exc:
            raise ResearchConsoleError(str(exc)) from exc

    def read_file(self, path: str) -> str:
        try:
            return self.runtime.read_file(path).decode("utf-8")
        except (BootRuntimeError, UnicodeDecodeError) as exc:
            raise ResearchConsoleError(str(exc)) from exc

    def suspend(self) -> dict[str, object]:
        try:
            return self.runtime.suspend()
        except BootRuntimeError as exc:
            raise ResearchConsoleError(str(exc)) from exc

    def resume(self) -> dict[str, object]:
        try:
            return self.runtime.resume()
        except BootRuntimeError as exc:
            raise ResearchConsoleError(str(exc)) from exc

    def heci_status(self) -> dict[str, Any]:
        """Return the transport status needed by the console status command."""

        return {
            "ready": self.model.ready,
            "host_ready": self.model.host_state.value == "ready",
            "me_ready": self.model.me_state.value == "ready",
            "interrupts": int(self.model.interrupts),
            "pending_requests": self.model.host_to_me_count,
            "pending_completions": self.model.me_to_host_count,
        }

    def send(self, opcode: int, payload: str | bytes = "") -> dict[str, Any]:
        """Send one opcode and UTF-8 payload through the synthetic bridge."""

        if isinstance(opcode, bool) or not isinstance(opcode, int):
            raise ResearchConsoleError("opcode must be a non-negative integer")
        if opcode < 0 or opcode > 0xFFFFFFFF:
            raise ResearchConsoleError("opcode must be between 0 and 0xffffffff")

        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        elif isinstance(payload, bytes):
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ResearchConsoleError("payload must be valid UTF-8") from exc
            payload_bytes = payload
        else:
            raise ResearchConsoleError("payload must be a string or bytes")

        try:
            result: BridgeResult = self.bridge.submit(opcode, payload_bytes)
        except (BridgeError, MEIError, ValueError) as exc:
            raise ResearchConsoleError(str(exc)) from exc

        completion = result.completion
        payload_text = completion.payload.decode("utf-8")
        self._last_completion = {
            "sequence": completion.sequence,
            "opcode": completion.opcode,
            "status": completion.status,
            "payload": payload_text,
            "payload_hex": completion.payload.hex(),
        }
        self._last_trace = result.events
        return {
            **self._last_completion,
            "events": list(result.events),
        }

    def trace(self) -> tuple[str, ...]:
        """Return the last deterministic bridge trace."""

        return self._last_trace

    def execute(self, command: str) -> str:
        """Execute one supported command and return stable console text."""

        if not isinstance(command, str):
            raise ResearchConsoleError("command must be a string")
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            raise ResearchConsoleError(f"invalid command syntax: {exc}") from exc
        if not tokens:
            raise ResearchConsoleError("command is empty")

        name = tokens[0].lower()
        if name == "help" and len(tokens) == 1:
            return self.help()
        if name == "state" and len(tokens) == 1:
            return self._json(self.state())
        if name == "reset" and len(tokens) == 1:
            return self._json(self.reset())
        if name == "heci-status" and len(tokens) == 1:
            return self._json({"transport": self.heci_status(), "runtime": self.runtime.heci_status()})
        if name == "boot" and len(tokens) == 1:
            return self._json(self.boot())
        if name == "dir" and len(tokens) <= 2:
            return self._json(list(self.list_dir(tokens[1] if len(tokens) == 2 else "/")))
        if name == "cat" and len(tokens) == 2:
            return self.read_file(tokens[1])
        if name == "suspend" and len(tokens) == 1:
            return self._json(self.suspend())
        if name == "resume" and len(tokens) == 1:
            return self._json(self.resume())
        if name == "trace" and len(tokens) == 1:
            return self._json(list(self.trace()))
        if name == "send" and len(tokens) >= 2:
            try:
                opcode = self._parse_opcode(tokens[1])
            except ValueError as exc:
                raise ResearchConsoleError("opcode must be an integer") from exc
            payload = " ".join(tokens[2:])
            return self._json(self.send(opcode, payload))
        raise ResearchConsoleError(f"unsupported command: {tokens[0]}")

    def run(self, command: str) -> str:
        """Alias for :meth:`execute` for callers treating the console as a runner."""

        return self.execute(command)

    @staticmethod
    def _parse_opcode(value: str) -> int:
        try:
            return int(value, 0)
        except ValueError:
            return int(value, 10)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = ["HELP_TEXT", "ResearchConsole", "ResearchConsoleError"]
