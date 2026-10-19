import hashlib
import json
import struct
import unittest
from pathlib import Path

from csme.runtime.module_loader import LoadedModule, ModuleCandidate
from csme.runtime.real_firmware_runtime import (
    RealRuntimeConfig,
    RealRuntimeStop,
    RealUnicornRuntime,
    UNICORN_AVAILABLE,
)


def _module(data: bytes, *, valid_extent: int | None = None) -> LoadedModule:
    candidate = ModuleCandidate(
        name="fixture",
        image_offset=0,
        size=len(data),
        guest_base=0x40000,
        flags=0,
        bounds_valid=True,
        load_status="bounded-uncompressed-candidate",
        compression="uncompressed",
        executable_candidate=True,
        declared_size=len(data),
        uncompressed_size=len(data),
    )
    return LoadedModule(
        candidate=candidate,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        valid_extent=valid_extent,
    )


@unittest.skipUnless(UNICORN_AVAILABLE, "Unicorn is required for real-byte runtime tests")
class RealFirmwareRuntimeTests(unittest.TestCase):
    def test_unmapped_write_records_exact_faulting_access_and_registers(self):
        # mov eax,0x06040004; mov ecx,0x06041288; mov dword ptr [eax-4],ecx
        program = bytes.fromhex("b804000406b9881204068948fc")
        trace = Path("qemu-work") / "traces" / "test-real-runtime-fault.jsonl"
        trace.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = RealUnicornRuntime(
                image=b"\0",
                image_sha256="0" * 64,
                trace_path=trace,
            ).run(_module(program), 0)
            events = [json.loads(line) for line in trace.read_text().splitlines()]
            faults = [event for event in events if event.get("type") == "invalid-memory"]
        finally:
            trace.unlink(missing_ok=True)

        self.assertEqual(len(faults), 1)
        fault = faults[0]
        self.assertEqual(fault["access"], "write")
        self.assertEqual(fault["address"], "0x6040000")
        self.assertEqual(fault["size"], 4)
        self.assertEqual(fault["value"], 0x06041288)
        self.assertEqual(fault["instruction"]["address"], "0x4000a")
        self.assertEqual(fault["instruction"]["bytes"], "8948fc")
        self.assertEqual(fault["registers"]["EAX"], "0x06040004")
        self.assertEqual(fault["registers"]["ECX"], "0x06041288")
        self.assertEqual(result["faulting_instruction"]["address"], "0x4000a")

    def test_control_flow_cannot_execute_capacity_beyond_valid_extent(self):
        program = b"\x90\x90\x90"
        trace = Path("qemu-work") / "traces" / "test-real-runtime-extent.jsonl"
        trace.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = RealUnicornRuntime(
                image=b"\0",
                image_sha256="0" * 64,
                trace_path=trace,
            ).run(_module(program, valid_extent=2), 0)
        finally:
            trace.unlink(missing_ok=True)

        self.assertIn("outside valid module extent", result["stop_reason"])
        self.assertEqual(result["faulting_instruction"]["address"], "0x40002")
        self.assertEqual(result["instructions_executed"], 3)

    def test_entry_offset_cannot_start_in_capacity_beyond_valid_extent(self):
        with self.assertRaises(RealRuntimeStop):
            RealUnicornRuntime(
                image=b"\0",
                image_sha256="0" * 64,
                trace_path=Path("qemu-work") / "traces" / "openme-unused.jsonl",
            ).run(_module(b"\x90\x90\x90", valid_extent=2), 2)

    def test_evidence_global_window_is_explicit_and_bounded(self):
        # The opt-in region is derived from the real rbe BSS correlation; the
        # default runtime still hard-stops the same address as unmapped.
        program = bytes.fromhex("b800000406b9881204068908")
        trace = Path("qemu-work") / "traces" / "test-real-runtime-evidence-global.jsonl"
        trace.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = RealUnicornRuntime(
                image=b"\0",
                image_sha256="0" * 64,
                trace_path=trace,
                config=RealRuntimeConfig(
                    evidence_global_base=0x06040000,
                    evidence_global_size=0x7004,
                ),
            ).run(_module(program), 0)
            events = [json.loads(line) for line in trace.read_text().splitlines()]
        finally:
            trace.unlink(missing_ok=True)

        self.assertNotIn("Invalid memory write", result["stop_reason"] or "")
        self.assertTrue(any(event.get("address") == "0x6040000" for event in events if event.get("type") == "memory"))

    def test_evidence_rom_memset_service_returns_to_real_call_site(self):
        # push 4; push 0; push 0x003fe000; call 0x103d; add esp,12; loop
        # The call remains a real instruction; only the external ROM ABI is
        # serviced because its bytes are not part of the SPI image.
        call_offset = 2 + 2 + 5
        call_address = 0x40000 + call_offset
        program = bytearray.fromhex("6a046a006800e03f00")
        program.extend(b"\xe8" + struct.pack("<i", 0x103D - (call_address + 5)))
        program.extend(bytes.fromhex("83c40cebfe"))
        trace = Path("qemu-work") / "traces" / "test-real-runtime-rom-memset.jsonl"
        trace.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = RealUnicornRuntime(
                image=b"\0",
                image_sha256="0" * 64,
                trace_path=trace,
                config=RealRuntimeConfig(
                    max_instructions=20,
                    rom_memset_address=0x103D,
                ),
            ).run(_module(bytes(program)), 0)
            events = [json.loads(line) for line in trace.read_text().splitlines()]
        finally:
            trace.unlink(missing_ok=True)

        services = [event for event in events if event.get("type") == "external-service"]
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["service"], "rom_memset")
        self.assertEqual(services[0]["destination"], "0x3fe000")
        self.assertEqual(services[0]["count"], 4)
        self.assertEqual(result["external_services"], 1)
        self.assertNotIn("Invalid memory fetch", result["stop_reason"] or "")

    def test_supplied_rom_bytes_execute_as_real_rom_region(self):
        # call 0x1000; loop.  The supplied byte at 0x1000 is an actual RET,
        # so the test verifies the real-ROM mapping path without a host stub.
        call_address = 0x40000
        program = b"\xe8" + struct.pack("<i", 0x1000 - (call_address + 5)) + b"\xeb\xfe"
        trace = Path("qemu-work") / "traces" / "test-real-runtime-rom-bytes.jsonl"
        trace.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = RealUnicornRuntime(
                image=b"\0",
                image_sha256="0" * 64,
                trace_path=trace,
                config=RealRuntimeConfig(
                    max_instructions=8,
                    rom_library_bytes=b"\xc3",
                ),
            ).run(_module(program), 0)
            events = [json.loads(line) for line in trace.read_text().splitlines()]
        finally:
            trace.unlink(missing_ok=True)

        rom_instructions = [
            event for event in events
            if event.get("type") == "instruction" and event.get("region") == "rom-library"
        ]
        self.assertEqual(len(rom_instructions), 1)
        self.assertEqual(rom_instructions[0]["address"], "0x1000")
        self.assertEqual(rom_instructions[0]["bytes"], "c3")
        self.assertIn("instruction timeout budget exhausted", result["stop_reason"] or "")


if __name__ == "__main__":
    unittest.main()
