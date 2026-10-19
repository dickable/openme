"""Board-specific physical SPI backup, image review, and explicit flashrom writes.

This tool cannot establish board compatibility, bypass flashrom restrictions,
or turn OpenME's QEMU development binary into a CSME flash image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def target(board: str, programmer: str, chip: str, size: int) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,79}", board):
        raise ValueError("board must be a specific identifier, not a path")
    if board.lower() in {"unknown", "skylake", "all", "everything", "generic"}:
        raise ValueError("a board/revision identifier is required, not a CPU family")
    if not programmer or programmer.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_:=,./\\-]+", programmer):
        raise ValueError("invalid flashrom programmer")
    if any(word in programmer.lower() for word in ("force", "this_is_not_a_laptop")):
        raise ValueError("flashrom board/probe override options are not supported")
    if not chip or chip.startswith("-") or not re.fullmatch(r"[A-Za-z0-9 ()_./+-]+", chip):
        raise ValueError("an exact flashrom chip name is required")
    if type(size) is not int or not 4096 <= size <= 128 * 1024 * 1024 or size & (size - 1):
        raise ValueError("chip size must be a power of two between 4 KiB and 128 MiB")
    return {"board": board, "programmer": programmer, "chip": chip, "size": size}


class Flashrom:
    def __init__(self, executable: str, identity: dict, directory: Path):
        self.executable, self.identity, self.directory = executable, identity, directory
        self.commands = []

    def operation(self, action: str, path: Path):
        if action not in {"read", "write", "verify"}:
            raise ValueError("unsupported operation")
        if action == "read" and path.exists():
            raise FileExistsError(f"refusing to overwrite readback: {path}")
        argv = [self.executable, "-p", self.identity["programmer"], "-c", self.identity["chip"],
                "--" + action, str(path)]
        log = self.directory / f"{len(self.commands):02d}-{action}.log"
        entry = {"command": argv, "log": str(log), "state": "started"}
        self.commands.append(entry)
        save(self.directory / "commands.json", {"operations": self.commands})
        # No shell, force flag, verification suppression, or automatic retry.
        # In particular, do not impose a timeout which kills a physical write.
        with log.open("xb") as stream:
            result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, check=False)
        entry.update(state="finished", returncode=result.returncode)
        save(self.directory / "commands.json", {"operations": self.commands})
        if result.returncode:
            raise RuntimeError(f"flashrom {action} failed ({result.returncode}); see {log}; no retry performed")


def checked_read(path: Path, size: int) -> bytes:
    if path.stat().st_size != size:
        raise ValueError(f"{path}: size does not match declared chip capacity {size}")
    data = path.read_bytes()
    if len(data) != size:
        raise ValueError(f"{path}: file size changed while reading")
    return data


def backup(identity: dict, output: Path, executable: str = "flashrom", backend=Flashrom) -> dict:
    identity = target(**identity)
    output.mkdir(parents=True, exist_ok=False)
    device = backend(executable, identity, output)
    first, second = output / "read-1.bin", output / "read-2.bin"
    device.operation("read", first)
    device.operation("read", second)
    a, b = checked_read(first, identity["size"]), checked_read(second, identity["size"])
    if a != b:
        raise ValueError("independent reads disagree; both retained; backup is unverified")
    if len(set(a)) == 1:
        raise ValueError("uniform flash contents; investigate connection/chip selection before proceeding")
    record = {"schema": 1, "target": identity, "sha256": sha256(a), "reads": [first.name, second.name]}
    save(output / "backup.json", record)
    return record


def load_backup(directory: Path) -> tuple[dict, bytes]:
    record = json.loads((directory / "backup.json").read_text(encoding="utf-8"))
    if record.get("schema") != 1 or record.get("reads") != ["read-1.bin", "read-2.bin"]:
        raise ValueError("unsupported backup record")
    identity = target(**record["target"])
    a = checked_read(directory / "read-1.bin", identity["size"])
    b = checked_read(directory / "read-2.bin", identity["size"])
    if a != b or sha256(a) != record["sha256"]:
        raise ValueError("backup files no longer match their recorded hash")
    return record, a


def differences(original: bytes, candidate: bytes) -> dict:
    if len(original) != len(candidate):
        raise ValueError("cannot compare different image capacities")
    ranges = []
    start = None
    changed = count = 0
    for i in range(len(original) + 1):
        different = i < len(original) and original[i] != candidate[i]
        if different:
            changed += 1
            if start is None:
                start = i
        elif start is not None:
            count += 1
            if len(ranges) < 256:
                ranges.append({"start": start, "end_exclusive": i,
                               "before_sha256": sha256(original[start:i]),
                               "after_sha256": sha256(candidate[start:i])})
            start = None
    return {"changed_bytes": changed, "range_count": count, "ranges": ranges,
            "ranges_truncated": count > len(ranges)}


def prepare(directory: Path, image: Path) -> tuple[dict, bytes]:
    record, original = load_backup(directory)
    candidate = checked_read(image, record["target"]["size"])
    if candidate[:4] in (b"\x02\xb0\xad\x1b", b"\x7fELF", b"MZ\x90\x00"):
        raise ValueError("an executable/QEMU image is not a full SPI image")
    diff = differences(original, candidate)
    if not diff["changed_bytes"]:
        raise ValueError("candidate equals baseline; no write is needed")
    return {"schema": 1, "target": record["target"], "baseline_sha256": record["sha256"],
            "candidate_sha256": sha256(candidate), "candidate": str(image.resolve()),
            "compatibility": "must be established for this board; byte comparison is not validation",
            **diff}, candidate


def write_image(directory: Path, image: Path, output: Path, *, confirm_board: str,
                confirm_sha256: str, recovery_note: str, execute: bool,
                executable: str = "flashrom", backend=Flashrom) -> dict:
    plan, candidate = prepare(directory, image)
    if not execute or confirm_board != plan["target"]["board"]:
        raise ValueError("write requires --execute and exact --confirm-board")
    if confirm_sha256.lower() != plan["candidate_sha256"]:
        raise ValueError("--confirm-sha256 must match the reviewed candidate")
    if len(recovery_note.strip()) < 12:
        raise ValueError("record a concrete recovery method with --recovery-note")
    output.mkdir(parents=True, exist_ok=False)
    state = {"plan": plan, "recovery_note": recovery_note, "phase": "prewrite", "verified": False}
    save(output / "result.json", state)
    device = backend(executable, plan["target"], output)
    try:
        # Freeze exactly the bytes reviewed, without touching the candidate or baseline.
        staged = output / "candidate.bin"
        with staged.open("xb") as stream:
            stream.write(candidate)
        current = output / "prewrite.bin"
        device.operation("read", current)
        if sha256(checked_read(current, plan["target"]["size"])) != plan["baseline_sha256"]:
            raise ValueError("live chip differs from backup; stopped before write")
        if sha256(staged.read_bytes()) != plan["candidate_sha256"]:
            raise ValueError("staged image changed; stopped before write")
        state["phase"] = "write-started"
        save(output / "result.json", state)
        device.operation("write", staged)  # flashrom's default verification remains enabled
        state["phase"] = "readback"
        save(output / "result.json", state)
        device.operation("verify", staged)
        readback = output / "readback.bin"
        device.operation("read", readback)
        if checked_read(readback, plan["target"]["size"]) != candidate:
            raise ValueError("post-write readback differs; do not reset/power-cycle; inspect logs and recovery")
        state.update(phase="complete", verified=True, readback_sha256=sha256(candidate))
    except BaseException as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        save(output / "result.json", state)
    return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("backup", help="read the physical chip twice and compare")
    read.add_argument("--board", required=True)
    read.add_argument("--programmer", required=True)
    read.add_argument("--chip", required=True)
    read.add_argument("--size", type=lambda x: int(x, 0), required=True)
    read.add_argument("--output", type=Path, required=True)
    read.add_argument("--flashrom", default="flashrom")
    plan = commands.add_parser("plan", help="offline candidate comparison; no hardware access")
    write = commands.add_parser("write", help="explicit physical write, verification, and readback")
    for child in (plan, write):
        child.add_argument("--backup", type=Path, required=True)
        child.add_argument("--image", type=Path, required=True)
    write.add_argument("--output", type=Path, required=True)
    write.add_argument("--flashrom", default="flashrom")
    write.add_argument("--confirm-board", required=True)
    write.add_argument("--confirm-sha256", required=True)
    write.add_argument("--recovery-note", required=True)
    write.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            result = backup(target(args.board, args.programmer, args.chip, args.size), args.output.resolve(), args.flashrom)
        elif args.command == "plan":
            result, _ = prepare(args.backup.resolve(), args.image.resolve())
        else:
            result = write_image(args.backup.resolve(), args.image.resolve(), args.output.resolve(),
                                 confirm_board=args.confirm_board, confirm_sha256=args.confirm_sha256,
                                 recovery_note=args.recovery_note, execute=args.execute, executable=args.flashrom)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(1, f"Flashing workflow stopped: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
