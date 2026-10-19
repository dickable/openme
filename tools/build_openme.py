"""Build OpenME's freestanding QEMU test firmware with GCC/binutils."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "qemu-work" / "openme-build"


def find_tool(name: str, directory: Path | None = None) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    candidates = [directory / (name + suffix)] if directory else []
    if found := shutil.which(name):
        candidates.append(Path(found))
    if os.name == "nt":
        candidates.append(Path("C:/msys64/ucrt64/bin") / (name + suffix))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise RuntimeError(f"{name} not found; provide --toolchain-dir")


def inspect_image(data: bytes) -> dict:
    if len(data) < 32:
        raise ValueError("image too short")
    magic, flags, checksum, header, base, end, bss, entry = struct.unpack_from("<8I", data)
    if magic != 0x1BADB002 or flags != 0x10000 or (magic + flags + checksum) & 0xFFFFFFFF:
        raise ValueError("invalid Multiboot header")
    if header != base or base != 0x100000 or end - base != len(data):
        raise ValueError("flat-image bounds mismatch")
    if not base + 32 <= entry < end <= bss < 0x200000:
        raise ValueError("invalid entry or BSS extent")
    return {"load_base": base, "load_end": end, "bss_end": bss, "entry": entry,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "target": "qemu-pc-i386", "format": "multiboot1-flat",
            "physical_flash_image": False}


def build(output: Path, directory: Path | None = None, profile: str = "dev") -> dict:
    if profile not in ("dev", "production", "hostdriver", "persist"):
        raise ValueError(f"unknown build profile: {profile}")
    output.mkdir(parents=True, exist_ok=True)
    gcc = find_tool("gcc", directory)
    bindir = Path(gcc).parent
    ld, objcopy, objdump = [find_tool(name, bindir) for name in ("ld", "objcopy", "objdump")]
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    # Keep compiler temporaries inside the build, not an inaccessible system dir.
    scratch = output / "tmp"
    scratch.mkdir(exist_ok=True)
    env.update(TMP=str(scratch.resolve()), TEMP=str(scratch.resolve()), TMPDIR=str(scratch.resolve()))
    commands = []

    def run(argv: list[str]) -> str:
        commands.append(argv)
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"command failed ({result.returncode}): {argv}\n{result.stdout}{result.stderr}")
        return result.stdout

    target = run([gcc, "-dumpmachine"]).strip()
    mingw = "mingw" in target
    flags = ["-m32", "-march=i686", "-std=c11", "-Os", "-g", "-Wall", "-Wextra", "-Werror",
             "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pic", "-fno-pie",
             "-fno-asynchronous-unwind-tables", "-fno-unwind-tables", "-mno-sse", "-mno-mmx",
             "-msoft-float", "-fno-ident", "-ffile-prefix-map=" + str(ROOT) + "=."]
    if mingw:
        flags += ["-fno-leading-underscore"]
    # Entry point by profile: dev = interactive shell; production = shell-free
    # autonomous loop; hostdriver = shell-free loop over the serial (COM2) HAL.
    entries = {
        "dev": "src/platform/qemu_x86/main.c",
        "production": "src/platform/qemu_x86/main_prod.c",
        "hostdriver": "src/platform/qemu_x86/main_hostdrv.c",
        "persist": "src/platform/qemu_x86/main_persist.c",
    }
    entry = entries[profile]
    sources = ["src/platform/qemu_x86/start.S", entry, "src/core.c",
               "src/mei/heci.c", "src/hal/hal.c", "src/hal/model/model_hal.c",
               "src/hal/gm45/gm45_hal.c", "src/hal/serial/serial_hal.c",
               "src/fs/flashfs.c", "src/fs/nor_model.c",
               "src/platform/support.c", "src/firmware.c", "src/service/echo.c"]
    objects = []
    for source in sources:
        obj = output / (Path(source).stem + ".o")
        run([gcc, *flags, "-c", source, "-o", str(obj)])
        objects.append(str(obj))
    linked = output / ("openme.pe" if mingw else "openme.elf")
    # PE is only an intermediate container. An RVA of zero makes BFD expose
    # .text at zero on extraction, so keep image-base zero and use the absolute
    # addresses from our linker script. Small file alignment avoids PE padding
    # extending the extracted flat image past image_load_end.
    ldflags = ["-m", "i386pe", "--image-base", "0", "--section-alignment", "16",
               "--file-alignment", "16", "--disable-reloc-section",
               "--no-insert-timestamp"] if mingw else ["-m", "elf_i386"]
    run([ld, *ldflags, "-T", "src/platform/qemu_x86/link.ld", "-Map", str(output / "openme.map"),
         "-o", str(linked), *objects])
    binary = output / "openme-qemu.bin"
    run([objcopy, "-O", "binary", "-j", ".text", "-j", ".rodata", "-j", ".data", str(linked), str(binary)])
    report = inspect_image(binary.read_bytes())
    report["profile"] = profile
    report["compiler"] = run([gcc, "--version"]).splitlines()[0]
    report["source_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                               for name in [*sources, "src/core.h", "src/mei/heci.h",
                                            "src/hal/hal.h", "src/hal/gm45/gm45_regs.h",
                                            "src/fs/flashfs.h", "src/platform/support.h",
                                            "src/firmware.h", "src/service/service.h",
                                            "src/capabilities.h", "src/platform/qemu_x86/link.ld"]}
    report["commands"] = commands
    (output / "openme.disasm").write_text(run([objdump, "-d", "-Mintel", str(linked)]), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--toolchain-dir", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--production", action="store_const", const="production", dest="profile",
                       help="build the shell-free production image")
    group.add_argument("--hostdriver", action="store_const", const="hostdriver", dest="profile",
                       help="build the shell-free image driven over COM2 (host-driver test)")
    group.add_argument("--persist", action="store_const", const="persist", dest="profile",
                       help="build the shell-free NOR snapshot test over COM2")
    parser.set_defaults(profile="dev")
    args = parser.parse_args()
    try:
        report = build(args.output.resolve(), args.toolchain_dir, args.profile)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Build failed: {exc}\n")
    print(f"[OpenME] Built {report['profile']} image: {report['bytes']} bytes; entry=0x{report['entry']:08x}")
    print(f"[OpenME] SHA256 {report['sha256']}")
    print(f"[OpenME] {args.output / 'openme-qemu.bin'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
