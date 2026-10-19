"""Prove NOR snapshot persistence across two independent QEMU process lifetimes.

The guest mounts and updates its own flashfs. This host only transports bytes,
checks them, and atomically commits the returned snapshot to a shared file.
This is COM2 snapshot persistence, not pflash or crash/power-loss durability.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time

try:
    from .build_openme import ROOT, build
    from .run_openme_qemu import command, qemu_path
except ImportError:
    from build_openme import ROOT, build
    from run_openme_qemu import command, qemu_path

NOR_SIZE = 2048
SECTOR_SIZE = 1024
CHUNK = 16
ACK = b"\x06"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_count(data: bytes) -> int:
    """Independent read-only check of the CURRENT OpenME flashfs record format."""
    if len(data) != NOR_SIZE:
        raise ValueError("wrong NOR extent")
    if data == b"\xff" * NOR_SIZE:
        return 0
    sectors = []
    for base in range(0, NOR_SIZE, SECTOR_SIZE):
        magic, generation = struct.unpack_from("<HI", data, base)
        if magic == 0x4653:
            sectors.append((generation, base))
    if not sectors:
        raise ValueError("no flashfs sector header")
    _, base = max(sectors, key=lambda item: item[0])  # same first-on-tie rule as flashfs_mount
    at, end = base + 8, base + SECTOR_SIZE
    count = None
    while at + 8 <= end:
        magic, key, state, length, crc = struct.unpack_from("<HBBHH", data, at)
        if magic == 0xffff:
            break
        if magic != 0x4f46 or length > 64 or at + 8 + length > end or state not in (0, 255):
            raise ValueError("invalid flashfs record")
        value = data[at + 8:at + 8 + length]
        if state == 255:
            if binascii.crc_hqx(bytes([key]) + struct.pack("<H", length) + value, 0xffff) != crc:
                raise ValueError("flashfs record CRC16 mismatch")
            if key == 0:
                if length != 4:
                    raise ValueError("invalid boot-counter record length")
                count, = struct.unpack("<I", value)
        at += 8 + length
    if count is None:
        raise ValueError("no live boot-counter record")
    return count


def remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("persistence run deadline exceeded")
    return left


def recvn(conn, size: int, deadline: float) -> bytes:
    if not 0 <= size <= NOR_SIZE:
        raise ValueError("unbounded COM2 read")
    data = bytearray()
    while len(data) < size:
        conn.settimeout(remaining(deadline))
        block = conn.recv(size - len(data))
        if not block:
            raise RuntimeError("COM2 closed before complete snapshot exchange")
        data.extend(block)
    return bytes(data)


def send(conn, data: bytes, deadline: float) -> None:
    conn.settimeout(remaining(deadline))
    conn.sendall(data)


def expect(conn, value: bytes, deadline: float) -> None:
    actual = recvn(conn, len(value), deadline)
    if actual != value:
        raise ValueError(f"COM2 expected {value.hex()}, got {actual.hex()}")


def exchange(conn, seed: bytes, deadline: float) -> tuple[bytes, int, int]:
    if len(seed) != NOR_SIZE:
        raise ValueError("seed is not a complete NOR image")
    expect(conn, b"OMP1" + struct.pack("<I", NOR_SIZE), deadline)
    send(conn, b"OMI1" + struct.pack("<II", len(seed), binascii.crc32(seed)), deadline)
    expect(conn, ACK, deadline)
    for at in range(0, len(seed), CHUNK):
        send(conn, seed[at:at + CHUNK], deadline)
        expect(conn, ACK, deadline)
    magic, length, crc, count, formatted = struct.unpack("<4s4I", recvn(conn, 20, deadline))
    if magic != b"OMO1" or length != NOR_SIZE or formatted not in (0, 1):
        raise ValueError("invalid returned snapshot header")
    send(conn, ACK, deadline)
    updated = bytearray()
    while len(updated) < length:
        updated.extend(recvn(conn, min(CHUNK, length - len(updated)), deadline))
        send(conn, ACK, deadline)
    if binascii.crc32(updated) != crc:
        raise ValueError("returned snapshot CRC32 mismatch")
    if snapshot_count(updated) != count:
        raise ValueError("reported count differs from persisted counter")
    return bytes(updated), count, formatted


def commit_snapshot(path: Path, expected: bytes, updated: bytes) -> None:
    """Replace only our validated test image; retain the caller's before/after artifacts."""
    snapshot_count(updated)
    if len(expected) != NOR_SIZE or path.read_bytes() != expected:
        raise ValueError("shared flash changed during QEMU run")
    fd, name = tempfile.mkstemp(prefix=".flash-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_once(qemu: Path, image: Path, output: Path, seed: bytes, timeout: float = 20) -> dict:
    output.mkdir()
    (output / "seed.bin").write_bytes(seed)
    info = {"passed": False, "seed_sha256": sha256(seed)}
    process = None
    deadline = time.monotonic() + timeout
    env = dict(os.environ)
    if os.name == "nt" and Path("C:/msys64/ucrt64/bin").is_dir():
        env["PATH"] = "C:/msys64/ucrt64/bin;" + env.get("PATH", "")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            argv = command(qemu, image, None,
                           ["-serial", f"file:{output / 'serial.log'}", "-serial",
                            f"tcp:127.0.0.1:{port},nodelay=on", "-nic", "none"],
                           output / "execution.log")
            info["command"] = argv
            with (output / "qemu.stderr.log").open("wb") as errors:
                process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=errors)
                info["pid"] = process.pid
                while True:
                    server.settimeout(min(0.25, remaining(deadline)))
                    try:
                        conn, _ = server.accept()
                        break
                    except socket.timeout:
                        if process.poll() is not None:
                            info["qemu_exit_code"] = process.returncode
                            raise RuntimeError("QEMU exited before COM2 connected; see qemu.stderr.log")
                with conn:
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    updated, count, formatted = exchange(conn, seed, deadline)
                    (output / "returned.bin").write_bytes(updated)
                    info.update(boot_count=count, formatted=formatted,
                                returned_sha256=sha256(updated))
                    code = process.wait(timeout=remaining(deadline))
                    info["qemu_exit_code"] = code
                    if code != 33:
                        raise RuntimeError(f"QEMU exit {code}, expected debug-exit 33")
            expected_count = snapshot_count(seed) + 1
            if count != expected_count or formatted != int(seed == b"\xff" * NOR_SIZE):
                raise AssertionError("boot counter or first-boot formatting mismatch")
            serial = (output / "serial.log").read_bytes()
            marker = f"persist: boot-count={count} formatted={formatted} net=none powered=0\r\n".encode()
            if marker not in serial or b"fault:" in serial:
                raise AssertionError(f"COM1 does not confirm the snapshot result: {serial!r}")
            trace = (output / "execution.log").read_text(encoding="utf-8", errors="replace")
            pcs = {int(pc, 16) for pc in re.findall(r"Trace \d+:.*?\[[0-9a-fA-F]+/([0-9a-fA-F]+)/", trace)}
            disasm = (image.parent / "openme.disasm").read_text(encoding="utf-8")
            info["function_dispatches"] = {}
            for symbol in ("om_nor_load", "om_firmware_boot", "flashfs_set", "om_nor_save"):
                match = re.search(r"^([0-9a-fA-F]+) <" + symbol + r">:", disasm, re.MULTILINE)
                if not match or int(match[1], 16) not in pcs:
                    raise AssertionError(f"missing execution evidence for {symbol}")
                info["function_dispatches"][symbol] = f"0x{int(match[1], 16):08x}"
            info["retired_instruction_count"] = None
            info["passed"] = True
    except BaseException as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        (output / "result.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def run_test(qemu: Path, output: Path) -> dict:
    report = {"passed": False, "kind": "COM2-NOR-snapshot-cold-process-restart", "boots": []}
    try:
        report["build"] = build(output / "build", profile="persist")
        image = output / "build/openme-qemu.bin"
        flash = output / "flash.bin"
        # output is always a new session directory; never erase an existing run.
        with flash.open("xb") as stream:
            stream.write(b"\xff" * NOR_SIZE)
        for number in (1, 2):
            seed = flash.read_bytes()  # second boot MUST read the actual committed host file
            boot_dir = output / f"boot-{number}"
            info = run_once(qemu, image, boot_dir, seed)
            report["boots"].append(info)
            if info["boot_count"] != number:
                raise AssertionError(f"boot {number} reported {info['boot_count']}")
            commit_snapshot(flash, seed, (boot_dir / "returned.bin").read_bytes())
        if report["boots"][0]["returned_sha256"] != report["boots"][1]["seed_sha256"]:
            raise AssertionError("cold restart did not reuse the first process's NOR snapshot")
        if snapshot_count(flash.read_bytes()) != 2:
            raise AssertionError("shared flash does not contain counter 2")
        report["final_flash_sha256"] = sha256(flash.read_bytes())
        report["passed"] = True
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path)
    parser.add_argument("--output", type=Path, help="new, nonexisting run directory (default: unique session)")
    args = parser.parse_args(argv)
    output = None
    try:
        qemu = qemu_path(args.qemu).resolve()
        if args.output:
            output = args.output.resolve()
            output.mkdir(parents=True, exist_ok=False)
        else:
            parent = ROOT / "qemu-work/openme-persist"
            parent.mkdir(parents=True, exist_ok=True)
            output = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
        print(f"[OpenME] Cold-persistence artifacts: {output}", flush=True)
        report = run_test(qemu, output)
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Persistence test failed: {exc}\nArtifacts: {output}\n")
    print("[OpenME] PASS: two QEMU processes; persisted boot counter 1 -> 2")
    print(f"[OpenME] Flash SHA256 {report['final_flash_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
