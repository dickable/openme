"""Boot source-built OpenME on QEMU PC; exercise its serial shell and C core."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import queue
import struct
import subprocess
import threading
import time

try:
    from .build_openme import ROOT, DEFAULT_OUT, inspect_image
except ImportError:
    from build_openme import ROOT, DEFAULT_OUT, inspect_image


def qemu_path(explicit: Path | None) -> Path:
    if explicit:
        return explicit.resolve(strict=True)
    if found := shutil.which("qemu-system-x86_64"):
        return Path(found)
    local = ROOT / "qemu-work/qemu-source-clean/build/qemu-system-x86_64.exe"
    if local.is_file():
        return local
    raise RuntimeError("QEMU not found; supply --qemu PATH")


def command(qemu: Path, image: Path, bios: Path | None, serial: list[str], trace: Path,
            *, execution_trace: bool = True) -> list[str]:
    args = [str(qemu), "-machine", "pc,accel=tcg", "-cpu", "qemu32", "-m", "32M",
            "-nodefaults", "-display", "none", "-monitor", "none", "-no-reboot",
            "-kernel", str(image), "-device", "isa-debug-exit,iobase=0xf4,iosize=4",
            "-d", "in_asm,exec" if execution_trace else "in_asm",
            "-dfilter", "0x100000..0x1fffff", "-D", str(trace), *serial]
    if bios:
        args += ["-L", str(bios)]
    elif (qemu.parent / "pc-bios/bios-256k.bin").is_file():
        args += ["-L", str(qemu.parent / "pc-bios")]
    return args


def run_test(qemu: Path, image: Path, output: Path, bios: Path | None = None) -> dict:
    info = inspect_image(image.read_bytes())
    output.mkdir(parents=True, exist_ok=True)
    transcript = bytearray()
    steps = []
    report = {"passed": False, "image": info, "checks": steps,
              "execution_kind": "source-built-openme-on-qemu-pc",
              "trace_kind": "translated instructions and TB dispatches; not a retired-instruction count"}
    env = dict(os.environ)
    if os.name == "nt" and Path("C:/msys64/ucrt64/bin").is_dir():
        env["PATH"] = "C:/msys64/ucrt64/bin;" + env.get("PATH", "")
    process = None
    worker = None
    test_deadline = time.monotonic() + 60
    try:
        with (output / "qemu.stderr.log").open("wb") as errors:
            argv = command(qemu, image, bios, ["-serial", "stdio"], output / "execution.log")
            report["command"] = argv
            process = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=errors)
            chunks = queue.Queue()

            def reader():
                while block := process.stdout.read1(4096):
                    chunks.put(block)
                chunks.put(b"")

            worker = threading.Thread(target=reader, daemon=True)
            worker.start()
            with process.stdin:

                def until(marker: bytes = b"openme:/# ") -> bytes:
                    received = bytearray()
                    deadline = min(time.monotonic() + 5, test_deadline)
                    while not received.endswith(marker):
                        try:
                            block = chunks.get(timeout=max(0.01, deadline - time.monotonic()))
                        except queue.Empty as exc:
                            raise RuntimeError("guest response timed out") from exc
                        if not block:
                            raise RuntimeError("guest serial connection closed before expected output")
                        received.extend(block)
                        transcript.extend(block)
                        if len(transcript) > 1024 * 1024 or time.monotonic() > deadline:
                            raise RuntimeError("guest output exceeded time/size limit")
                    return bytes(received)

                def shell(line: str, expected: bytes | None = None) -> bytes:
                    # QEMU's Windows stdio backend drops input when the UART
                    # FIFO is full (char-win-stdio.c). The guest's echo is an
                    # acknowledgement, so send one byte per echo, not a burst.
                    # This also works on Unix without timing-dependent sleeps.
                    for byte in line.encode("ascii"):
                        process.stdin.write(bytes([byte]))
                        process.stdin.flush()
                        until(b"\b \b" if byte in (8, 127) else bytes([byte]))
                    # Windows QEMU deliberately strips CR on redirected stdin.
                    process.stdin.write(b"\n")
                    process.stdin.flush()
                    reply = until()
                    if expected is not None and expected not in reply:
                        raise AssertionError(f"missing {expected!r} in guest response to {line[:40]!r}: {reply!r}")
                    return reply

                banner = until()
                if b"source-built firmware / QEMU PC test target" not in banner:
                    raise AssertionError(f"unexpected boot output: {banner!r}")
                steps.append("boot-to-shell")
                shell("version", b"target=qemu-pc-i386")
                shell("status", b"state=ready")
                shell("help", b"frame HEX")
                shell("versiox\bn", b"OpenME 0.1;")
                steps.append("shell-commands-and-backspace")

                shell("hal", b"hal=model gen=emulation bringup=ok h2m=ok m2h=ok")
                steps.append("hal-interface-bidirectional")

                shell("fs", b"fs=flashfs selftest=ok")
                steps.append("flash-filesystem-selftest")

                shell("platform", b"platform=emulation support=ok")
                steps.append("platform-support-guard")

                shell("boot", b"net=none result=ok")
                steps.append("full-firmware-bringup-no-network")

                shell("run", b"run: boot=ok host-start=ok")
                steps.append("autonomous-service-loop-over-hal")

                shell("time", b"time: advancing=yes")
                steps.append("hal-timebase")

                shell("convo", b"convo: service-dispatch=ok")
                steps.append("service-dispatch-full-conversation")

                shell("gate", b"gate: dormant=ok active=ok")
                steps.append("dormant-until-powered-on")

                shell("persist", b"persist: boot-count=1,2,3 survives-reboot=ok")
                steps.append("reboot-persistence")

                shell("echo openme > 9", b"written")
                shell("cat 9", b"openme")
                shell("ls", b"9  6 bytes")
                steps.append("sh-style-filesystem")

                seq = 0

                def packet(op: int, payload: bytes = b"", status: int = 0,
                           expected: bytes = b"", mutate=None):
                    nonlocal seq
                    seq += 1
                    raw = struct.pack("<HBBBBHIHH", 0x4f4d, 1, 0, op, 0, 0, seq, len(payload), 0) + payload
                    if mutate:
                        raw = mutate(raw)
                    reply = shell("frame " + raw.hex())
                    match = re.search(rb"\r\nreply ([0-9a-f]+)\r\n", reply)
                    if not match:
                        raise AssertionError(f"missing frame response: {reply!r}")
                    actual = bytes.fromhex(match[1].decode())
                    want = struct.pack("<HBBBBHIHH", 0x4f4d, 1, 1 if not status else 3,
                                       op, status, 0, seq, len(expected), 0) + expected
                    if actual != want:
                        raise AssertionError(f"opcode {op}: expected {want.hex()}, got {actual.hex()}")

                packet(7, b"not-connected", status=7)
                packet(2, expected=b"OPENME-TRANSPORT-1")
                packet(3, expected=b"openme.echo")
                packet(4, b"openme.echo", expected=b"openme.echo|1|256")
                packet(5, b"unknown", status=8)
                packet(5, b"openme.echo")
                packet(6, expected=b"1")
                packet(7, b"OpenME in C", expected=b"OpenME in C")
                packet(7, bytes(range(256)), expected=bytes(range(256)))
                steps.append("negotiate-discover-connect-and-256-byte-echo")
                packet(1, mutate=lambda b: b[:6] + b"\x01" + b[7:], status=4)
                shell("status", b"state=connected")
                packet(7, status=9, mutate=lambda b: b[:12] + b"\x01\x01" + b[14:])
                packet(7, status=1, mutate=lambda b: b"\x00" + b[1:])
                shell("frame f", b"error: invalid frame hex")
                shell("x" * 600, b"error: line too long")
                shell("status", b"state=connected")
                steps.append("malformed-frame-and-line-overflow-recovery")
                packet(9)
                packet(7, status=7)
                packet(10)
                packet(7, status=7)
                packet(5, b"openme.echo")
                packet(8)
                packet(1)
                shell("status", b"state=ready")
                steps.append("suspend-resume-disconnect-reset")

                heci_submissions = 0
                heci_responses = 0

                def wire(payload: bytes, me: int = 0, host: int = 0, complete: bool = True):
                    return struct.pack("<I", me | host << 8 | len(payload) << 16 |
                                       int(complete) << 31) + payload

                def heci_send(raw: bytes, expected: str = "ok"):
                    nonlocal heci_submissions
                    heci_submissions += 1
                    answer = shell("heci " + raw.hex())
                    want = f"\r\nheci status={expected}\r\nopenme:/# ".encode()
                    if answer != want:
                        raise AssertionError(f"HECI expected {want!r}, got {answer!r}")

                def heci_pop(expected: bytes | None = None):
                    nonlocal heci_responses
                    answer = shell("heci-poll")
                    want = ("\r\nheci empty\r\nopenme:/# " if expected is None else
                            f"\r\nheci reply {expected.hex()}\r\nopenme:/# ").encode()
                    if answer != want:
                        raise AssertionError(f"HECI expected {want!r}, got {answer!r}")
                    if expected is not None:
                        heci_responses += 1

                def hbm(hex_payload: str, expected: str = "ok"):
                    heci_send(wire(bytes.fromhex(hex_payload)), expected)

                shell("heci-reset", b"heci reset")
                hbm("04000000", "invalid-state")
                hbm("01000202")  # Linux host 2.2 request -> base 1.0 negotiation
                heci_pop(bytes.fromhex("0000048081000001"))
                hbm("04000000")
                heci_pop(wire(bytes.fromhex("8400000080") + bytes(31)))
                hbm("05070000")
                heci_pop(bytes.fromhex("00001c80850700006e65706f656d454d9a710000000000010101000000010000"))
                hbm("06070300")
                heci_pop(wire(bytes.fromhex("86070300")))
                grant = wire(bytes.fromhex("0807030000000000"))
                heci_pop(grant)
                heci_pop()
                steps.append("hbm-1.0-negotiation-enumeration-properties-connect")

                payload = bytes(range(256))
                heci_send(wire(payload[:99], 7, 3, False))
                heci_pop()
                heci_send(wire(payload[99:], 7, 4), "wrong-address")
                heci_send(wire(payload[99:], 7, 3))
                heci_pop()  # no host read credit; no fabricated response
                heci_send(wire(b"extra", 7, 3), "no-credit")
                heci_send(grant)
                heci_send(grant, "no-credit")
                for at in range(0, 256, 64):
                    heci_pop(wire(payload[at:at + 64], 7, 3, at == 192))
                heci_pop(grant)
                heci_pop()
                steps.append("hbm-bidirectional-credits-and-fragmented-256-byte-echo")

                heci_send(bytes.fromhex("0000048204000000"), "unsupported")
                heci_send(bytes.fromhex("00000480040000"), "malformed")
                heci_send(wire(bytes(257), 7, 3), "too-large")
                hbm("13000000", "unsupported")
                for _ in range(4):
                    hbm("06070400")
                hbm("06070400", "queue-full")
                for _ in range(4):
                    heci_pop(wire(bytes.fromhex("86070403")))
                heci_pop()
                steps.append("hbm-malformed-unsupported-mtu-and-queue-backpressure")

                heci_send(wire(b"partial", 7, 3, False))
                hbm("07070300")
                heci_pop(wire(bytes.fromhex("87070300")))
                heci_pop()
                hbm("06070300")
                heci_pop(wire(bytes.fromhex("86070300")))
                heci_pop(grant)
                heci_send(wire(b"must-not-survive-reset", 7, 3))
                shell("heci-reset", b"heci reset")
                heci_pop()
                heci_send(grant, "invalid-state")
                hbm("01000001")
                heci_pop(wire(bytes.fromhex("81010001")))
                hbm("02000000")
                heci_pop(wire(bytes.fromhex("82000000")))
                heci_pop()
                steps.append("hbm-disconnect-clears-fragments-and-reset-clears-credits")
                report["heci_submissions"] = heci_submissions
                report["heci_response_packets"] = heci_responses
                process.stdin.write(b"halt\n")
                process.stdin.flush()
                until(b"OpenME halted\r\n")
            code = process.wait(timeout=5)
            report["qemu_exit_code"] = code
            if code != 33:  # isa-debug-exit (0x10 << 1) | 1
                raise AssertionError(f"guest halt returned {code}, expected 33")
            trace = (output / "execution.log").read_text(encoding="utf-8", errors="replace")
            pcs = {int(pc, 16) for pc in re.findall(r"Trace \d+:.*?\[[0-9a-fA-F]+/([0-9a-fA-F]+)/", trace)}
            firmware_pcs = sorted(pc for pc in pcs if info["load_base"] <= pc < info["load_end"])
            if info["entry"] not in firmware_pcs:
                raise AssertionError("QEMU trace does not record dispatch to the firmware entry")
            report["executed_tb_start_addresses"] = [f"0x{pc:08x}" for pc in firmware_pcs]
            disassembly = (image.parent / "openme.disasm").read_text(encoding="utf-8")
            report["heci_function_dispatches"] = {}
            for name in ("om_heci_receive", "om_heci_transmit"):
                symbol = re.search(r"^([0-9a-fA-F]+) <" + name + r">:", disassembly, re.MULTILINE)
                if not symbol or int(symbol[1], 16) not in firmware_pcs:
                    raise AssertionError(f"no QEMU dispatch evidence for {name}")
                report["heci_function_dispatches"][name] = f"0x{int(symbol[1], 16):08x}"
            report["retired_instruction_count"] = None
            steps.append("guest-requested-halt")
            report["frame_exchanges"] = seq
            report["passed"] = True
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if process:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            if worker:
                worker.join(timeout=3)
            process.stdout.close()
        (output / "serial.log").write_bytes(transcript)
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_OUT / "openme-qemu.bin")
    parser.add_argument("--qemu", type=Path)
    parser.add_argument("--bios-dir", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT / "qemu-test")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    try:
        qemu = qemu_path(args.qemu)
        image = args.image.resolve(strict=True)
        inspect_image(image.read_bytes())
        output = args.output.resolve()
        if args.interactive:
            output.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            if os.name == "nt":
                env["PATH"] = "C:/msys64/ucrt64/bin;" + env.get("PATH", "")
            # A user may leave this polling shell open for hours. Log unique
            # translations, not an unbounded stream of idle-loop dispatches.
            argv = command(qemu, image, args.bios_dir, ["-serial", "stdio"],
                           output / "interactive-translations.log", execution_trace=False)
            print("[OpenME] Starting source-built firmware. Type help or halt.", flush=True)
            code = subprocess.call(argv, env=env)
            return 0 if code == 33 else code or 1
        result = run_test(qemu, image, output, args.bios_dir)
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"QEMU test failed: {exc}\nLogs: {args.output}\n")
    print(f"[OpenME] PASS: {len(result['checks'])} QEMU checks, {result['frame_exchanges']} frame exchanges")
    print(f"[OpenME] HBM: {result['heci_submissions']} submissions, {result['heci_response_packets']} response packets")
    print(f"[OpenME] Trace and serial transcript: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
