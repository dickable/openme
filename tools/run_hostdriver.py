"""Pass-2 host-driver test.

Drives OpenME as a SEPARATE PROCESS over a second serial port (COM2): QEMU runs
the shell-free `hostdriver` image whose HECI transport is COM2 (TCP-backed), and
this script plays the host, performing a real HECI conversation and asserting the
replies. It proves the firmware's autonomous service loop works over a real byte
stream, not an in-guest simulation.

Framing on COM2: each HECI packet is prefixed with a 2-byte little-endian length.
"""
from __future__ import annotations

import argparse
import os
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from .build_openme import ROOT, build
    from .run_openme_qemu import qemu_path
except ImportError:
    from build_openme import ROOT, build
    from run_openme_qemu import qemu_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path)
    args = parser.parse_args(argv)

    qemu = qemu_path(args.qemu)
    out = (ROOT / "qemu-work" / "openme-hostdrv").resolve()
    build(out, None, "hostdriver")  # shell-free image whose HAL is COM2
    image = out / "openme-qemu.bin"

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    qargv = [str(qemu), "-machine", "pc,accel=tcg", "-cpu", "qemu32", "-m", "32M",
             "-nodefaults", "-display", "none", "-monitor", "none", "-no-reboot",
             "-kernel", str(image), "-serial", "stdio",
             "-serial", f"tcp:127.0.0.1:{port}"]  # COM1=stdio, COM2=TCP (QEMU connects)
    if (qemu.parent / "pc-bios/bios-256k.bin").is_file():
        qargv += ["-L", str(qemu.parent / "pc-bios")]

    env = dict(os.environ)
    if os.name == "nt" and Path("C:/msys64/ucrt64/bin").is_dir():
        env["PATH"] = "C:/msys64/ucrt64/bin;" + env.get("PATH", "")

    proc = subprocess.Popen(qargv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    com1 = queue.Queue()

    def reader():
        acc = bytearray()
        while True:
            block = proc.stdout.read1(256) if hasattr(proc.stdout, "read1") else proc.stdout.read(256)
            if not block:
                break
            acc.extend(block)
            com1.put(bytes(acc))

    threading.Thread(target=reader, daemon=True).start()

    conn = None
    try:
        srv.settimeout(20)
        conn, _ = srv.accept()
        conn.settimeout(10)

        deadline = time.monotonic() + 20
        seen = b""
        while b"hostdriver ready" not in seen:
            if time.monotonic() > deadline:
                raise RuntimeError(f"no readiness banner on COM1; got {seen!r}")
            try:
                seen = com1.get(timeout=1)
            except queue.Empty:
                if proc.poll() is not None:
                    raise RuntimeError("QEMU exited before becoming ready")

        def recvn(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    raise RuntimeError("COM2 connection closed")
                buf += chunk
            return buf

        def recvf() -> bytes:
            return recvn(struct.unpack("<H", recvn(2))[0])

        def sendf(pkt: bytes) -> None:
            conn.sendall(struct.pack("<H", len(pkt)) + pkt)

        checks = 0

        def expect(got: bytes, want: bytes, what: str) -> None:
            nonlocal checks
            if got != want:
                raise AssertionError(f"{what}: expected {want.hex()}, got {got.hex()}")
            checks += 1

        # A real HECI conversation, host -> ME, over the serial wire.
        sendf(bytes.fromhex("0000048001000202"))                   # HOST_START
        expect(recvf(), bytes.fromhex("0000048081000001"), "host-start reply")
        sendf(bytes.fromhex("0000048006070300"))                   # CONNECT client7 host3
        expect(recvf(), bytes.fromhex("0000048086070300"), "connect reply")
        expect(recvf(), bytes.fromhex("000008800807030000000000"), "ME flow-control grant")
        data = bytes.fromhex("0703058068656c6c6f")                 # DATA "hello"
        sendf(data)
        sendf(bytes.fromhex("000008800807030000000000"))           # host grants read credit
        expect(recvf(), data, "echoed data")

        print(f"[OpenME] host-driver PASS: {checks} HECI checks over COM2 (separate process)")
        return 0
    except BaseException as exc:
        sys.stderr.write(f"host-driver test FAILED: {type(exc).__name__}: {exc}\n")
        return 1
    finally:
        try:
            if conn:
                conn.close()
        except OSError:
            pass
        srv.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
