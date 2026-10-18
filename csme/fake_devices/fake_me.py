"""Deterministic, software-only OpenME host-facing model.

This is a project-defined test model. It is not Intel ME firmware and does not
claim compatibility with Intel's private firmware services or security flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    RESET = "reset"
    READY = "ready"
    NEGOTIATING = "negotiating"
    ENUMERATING = "enumerating"
    IDLE = "idle"
    CONNECTED = "connected"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class Request:
    command: str
    client: str = ""
    payload: bytes = b""
    version: int = 1


@dataclass(frozen=True)
class Response:
    command: str
    status: str
    payload: bytes = b""
    event: int = 0


@dataclass(frozen=True)
class Client:
    name: str
    protocol: int
    maximum_message: int


@dataclass
class FakeME:
    """A bounded state machine for deterministic host-side testing."""

    maximum_message: int = 256
    credits: int = 4
    state: State = State.RESET
    event: int = 0
    connected_client: str = ""
    trace: list[dict] = field(default_factory=list)
    clients: tuple[Client, ...] = (
        Client("openme.control", protocol=1, maximum_message=64),
        Client("openme.echo", protocol=1, maximum_message=256),
    )

    def _record(self, direction: str, message: str, **details) -> None:
        self.event += 1
        self.trace.append({"event": self.event, "direction": direction, "message": message, **details})

    def _respond(self, request: Request, status: str, payload: bytes = b"") -> Response:
        response = Response(request.command, status, payload, self.event)
        self._record("device", request.command, status=status, payload=payload.hex())
        return response

    def reset(self) -> None:
        self.state = State.READY
        self.connected_client = ""
        self._record("device", "reset", state=self.state.value)

    def _known_client(self, name: str) -> Client | None:
        return next((client for client in self.clients if client.name == name), None)

    def handle(self, request: Request) -> Response:
        self._record(
            "host", request.command, client=request.client,
            payload=request.payload.hex(), version=request.version,
        )
        command = request.command.upper()
        if command == "RESET":
            self.reset()
            return self._respond(request, "ok")
        if command == "START":
            if self.state != State.READY:
                return self._respond(request, "invalid-state")
            if request.version != 1:
                return self._respond(request, "unsupported-version")
            self.state = State.NEGOTIATING
            return self._respond(request, "ok", b"OPENME-TRANSPORT-1")
        if command == "ENUMERATE":
            if self.state not in (State.NEGOTIATING, State.ENUMERATING):
                return self._respond(request, "invalid-state")
            self.state = State.ENUMERATING
            payload = b"\0".join(client.name.encode("ascii") for client in self.clients)
            self.state = State.IDLE
            return self._respond(request, "ok", payload)
        if command == "PROPERTIES":
            client = self._known_client(request.client)
            if self.state not in (State.ENUMERATING, State.IDLE) or client is None:
                return self._respond(request, "unsupported-client" if client is None else "invalid-state")
            payload = f"{client.name}|{client.protocol}|{client.maximum_message}".encode("ascii")
            return self._respond(request, "ok", payload)
        if command == "CONNECT":
            if self.state != State.IDLE:
                return self._respond(request, "invalid-state")
            if self._known_client(request.client) is None:
                return self._respond(request, "unsupported-client")
            self.connected_client = request.client
            self.state = State.CONNECTED
            return self._respond(request, "ok")
        if command == "FLOW_CONTROL":
            if self.state != State.CONNECTED or request.client != self.connected_client:
                return self._respond(request, "invalid-state")
            return self._respond(request, "ok", str(self.credits).encode("ascii"))
        if command == "DATA":
            client = self._known_client(request.client)
            if self.state != State.CONNECTED or request.client != self.connected_client:
                return self._respond(request, "invalid-state")
            if client is None:
                return self._respond(request, "unsupported-client")
            if len(request.payload) > min(self.maximum_message, client.maximum_message):
                return self._respond(request, "message-too-large")
            if client.name != "openme.echo":
                return self._respond(request, "unsupported")
            return self._respond(request, "ok", request.payload)
        if command == "DISCONNECT":
            if self.state != State.CONNECTED or request.client != self.connected_client:
                return self._respond(request, "invalid-state")
            self.connected_client = ""
            self.state = State.IDLE
            return self._respond(request, "ok")
        if command == "SUSPEND":
            if self.state not in (State.IDLE, State.CONNECTED):
                return self._respond(request, "invalid-state")
            self.state = State.SUSPENDED
            return self._respond(request, "ok")
        if command == "RESUME":
            if self.state != State.SUSPENDED:
                return self._respond(request, "invalid-state")
            self.state = State.IDLE
            self.connected_client = ""
            return self._respond(request, "ok")
        return self._respond(request, "unsupported-command")

