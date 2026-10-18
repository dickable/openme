"""Synthetic ME boot and runtime environment.

This module models the shape of a platform runtime without loading or
executing firmware bytes.  The manifest, modules, memory map, services, HECI
transport, power states, and MFS-like files are all project-authored synthetic
data.  It is a scaffold for deterministic experiments, not Intel firmware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class BootRuntimeError(RuntimeError):
    """Raised when a synthetic runtime operation is out of sequence."""


class BootPhase(str, Enum):
    RESET = "reset"
    ROM = "rom"
    MANIFEST_ACCEPTED = "manifest-accepted"
    MEMORY_READY = "memory-ready"
    SERVICES_READY = "services-ready"
    HECI_READY = "heci-ready"
    RUNNING = "running"
    SUSPENDED = "suspended"
    FAILED = "failed"


@dataclass(frozen=True)
class SyntheticModule:
    name: str
    role: str


@dataclass(frozen=True)
class SyntheticBootManifest:
    platform: str = "openme-synthetic-skylake"
    version: str = "0.1"
    modules: tuple[SyntheticModule, ...] = (
        SyntheticModule("romp", "reset coordinator"),
        SyntheticModule("kernel", "task scheduler"),
        SyntheticModule("syslib", "runtime services"),
        SyntheticModule("bup", "early platform setup"),
        SyntheticModule("heci", "host transport"),
        SyntheticModule("storage", "synthetic MFS service"),
        SyntheticModule("pm", "power management"),
    )


@dataclass(frozen=True)
class MemoryMapEntry:
    name: str
    base: int
    size: int
    kind: str


@dataclass(frozen=True)
class BootEvent:
    step: int
    phase: str
    message: str


class SyntheticMFS:
    """In-memory, host-independent directory and file model."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {
            "/etc/openme/platform": b"openme-synthetic-skylake\n",
            "/etc/openme/version": b"0.1\n",
            "/etc/openme/modules": b"romp kernel syslib bup heci storage pm\n",
            "/sys/heci/status": b"reset\n",
            "/sys/power/state": b"running\n",
            "/var/log/boot": b"",
        }

    @staticmethod
    def _normalize(path: str) -> str:
        if not isinstance(path, str) or not path.startswith("/"):
            raise BootRuntimeError("MFS paths must be absolute")
        parts = [part for part in path.split("/") if part]
        if any(part in {".", ".."} for part in parts):
            raise BootRuntimeError("MFS traversal is not supported")
        return "/" + "/".join(parts) if parts else "/"

    def read(self, path: str) -> bytes:
        path = self._normalize(path)
        if path not in self._files:
            raise BootRuntimeError(f"MFS file not found: {path}")
        return self._files[path]

    def list_dir(self, path: str = "/") -> tuple[str, ...]:
        path = self._normalize(path).rstrip("/") or "/"
        prefix = "/" if path == "/" else path + "/"
        names: set[str] = set()
        for file_path in self._files:
            if not file_path.startswith(prefix):
                continue
            remainder = file_path[len(prefix) :]
            if remainder:
                names.add(remainder.split("/", 1)[0])
        return tuple(sorted(names))

    def set_runtime_state(self, state: str) -> None:
        self._files["/sys/heci/status"] = f"{state}\n".encode("ascii")
        self._files["/sys/power/state"] = f"{state}\n".encode("ascii")

    def append_boot_event(self, event: BootEvent) -> None:
        line = f"{event.step:02d} {event.phase} {event.message}\n"
        self._files["/var/log/boot"] += line.encode("ascii")


class SyntheticMERuntime:
    """Deterministic boot/service model with no firmware-byte input."""

    memory_map = (
        MemoryMapEntry("rom", 0x00000000, 0x00010000, "read-only synthetic"),
        MemoryMapEntry("sram", 0x00010000, 0x00010000, "read-write synthetic"),
        MemoryMapEntry("dram", 0x10000000, 0x01000000, "read-write synthetic"),
        MemoryMapEntry("heci-mmio", 0xF0000000, 0x00001000, "synthetic device"),
        MemoryMapEntry("spi-mmio", 0xF0010000, 0x00001000, "synthetic device"),
        MemoryMapEntry("pm-mmio", 0xF0020000, 0x00001000, "synthetic device"),
    )

    def __init__(
        self,
        manifest: SyntheticBootManifest | None = None,
        mfs: SyntheticMFS | None = None,
    ) -> None:
        self.manifest = manifest or SyntheticBootManifest()
        self.mfs = mfs or SyntheticMFS()
        self.phase = BootPhase.RESET
        self.events: list[BootEvent] = []
        self.loaded_modules: list[str] = []
        self.services: list[str] = []
        self._step = 0
        self.reset()

    def reset(self) -> None:
        self.phase = BootPhase.RESET
        self.events = []
        self.loaded_modules = []
        self.services = []
        self._step = 0
        self.mfs.set_runtime_state("reset")

    def _event(self, phase: BootPhase, message: str) -> None:
        self._step += 1
        event = BootEvent(self._step, phase.value, message)
        self.events.append(event)
        self.mfs.append_boot_event(event)

    def boot(self) -> dict[str, object]:
        """Boot the project-authored synthetic manifest through all phases."""

        self.reset()
        self.phase = BootPhase.ROM
        self._event(self.phase, "synthetic reset vector entered")
        if self.manifest.platform != "openme-synthetic-skylake":
            self.phase = BootPhase.FAILED
            self._event(self.phase, "unsupported synthetic platform")
            raise BootRuntimeError("unsupported synthetic platform")

        self.phase = BootPhase.MANIFEST_ACCEPTED
        self._event(self.phase, "synthetic manifest accepted; no cryptographic check performed")
        self.phase = BootPhase.MEMORY_READY
        self._event(self.phase, "synthetic ROM, SRAM, DRAM, and MMIO map installed")

        self.loaded_modules = [module.name for module in self.manifest.modules]
        self.services = ["spi", "storage", "power", "heci"]
        self.phase = BootPhase.SERVICES_READY
        self._event(self.phase, "synthetic services initialized")
        self.phase = BootPhase.HECI_READY
        self._event(self.phase, "host transport ready")
        self.phase = BootPhase.RUNNING
        self.mfs.set_runtime_state("running")
        self._event(self.phase, "synthetic runtime entered")
        return self.state()

    def _require(self, *phases: BootPhase) -> None:
        if self.phase not in phases:
            expected = ", ".join(phase.value for phase in phases)
            raise BootRuntimeError(
                f"operation requires phase {expected}; current phase is {self.phase.value}"
            )

    def suspend(self) -> dict[str, object]:
        self._require(BootPhase.RUNNING)
        self.phase = BootPhase.SUSPENDED
        self.mfs.set_runtime_state("suspended")
        self._event(self.phase, "power state suspended")
        return self.state()

    def resume(self) -> dict[str, object]:
        self._require(BootPhase.SUSPENDED)
        self.phase = BootPhase.RUNNING
        self.mfs.set_runtime_state("running")
        self._event(self.phase, "power state resumed")
        return self.state()

    def heci_status(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "ready": self.phase in {BootPhase.HECI_READY, BootPhase.RUNNING},
            "services": tuple(self.services),
        }

    def state(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "platform": self.manifest.platform,
            "version": self.manifest.version,
            "loaded_modules": tuple(self.loaded_modules),
            "services": tuple(self.services),
            "memory_map": tuple(entry.name for entry in self.memory_map),
            "event_count": len(self.events),
        }

    def list_dir(self, path: str = "/") -> tuple[str, ...]:
        self._require(BootPhase.RUNNING, BootPhase.SUSPENDED)
        return self.mfs.list_dir(path)

    def read_file(self, path: str) -> bytes:
        self._require(BootPhase.RUNNING, BootPhase.SUSPENDED)
        return self.mfs.read(path)


SyntheticMEPlatform = SyntheticMERuntime


__all__ = [
    "BootEvent",
    "BootPhase",
    "BootRuntimeError",
    "MemoryMapEntry",
    "SyntheticBootManifest",
    "SyntheticMEPlatform",
    "SyntheticMERuntime",
    "SyntheticMFS",
    "SyntheticModule",
]
