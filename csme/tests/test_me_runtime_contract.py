import unittest

from csme.runtime.me_runtime_contract import (
    BackendStep,
    ContractError,
    DeterministicMemory,
    Interrupt,
    InterruptController,
    ListTraceSink,
    MemoryRegion,
    MERuntimeContract,
    MMIOAccess,
    MMIOBus,
    RegisterFile,
    RuntimeState,
    SyscallDispatcher,
    SyscallRequest,
    SyscallResult,
)


class CountingBackend:
    def __init__(self):
        self.count = 0

    def reset(self, runtime):
        self.count = 0

    def execute_step(self, runtime, instruction_budget):
        self.count += 1
        runtime.registers.set("pc", runtime.registers.get("pc") + instruction_budget)
        return BackendStep(instructions=instruction_budget, cycles=instruction_budget * 2)

    def snapshot(self, runtime):
        return str(self.count).encode("ascii")

    def restore(self, runtime, snapshot):
        self.count = int(snapshot.decode("ascii"))


class RegisterMMIO:
    def __init__(self):
        self.value = 0

    def read(self, access: MMIOAccess):
        return self.value

    def write(self, access: MMIOAccess):
        self.value = access.value


def make_runtime():
    memory = DeterministicMemory()
    memory.map_region(MemoryRegion("rom", 0x0000, 0x10, True), b"ROM")
    memory.map_region(MemoryRegion("ram", 0x1000, 0x10, False), b"RAM")
    registers = RegisterFile(["pc", "status"], {"pc": 0x100, "status": 1})
    interrupts = InterruptController()
    mmio = MMIOBus()
    mmio.map(0xF000, 4, RegisterMMIO())
    state = RuntimeState(memory, registers, SyscallDispatcher(), mmio, interrupts)
    trace = ListTraceSink()
    backend = CountingBackend()
    return MERuntimeContract(state, backend, trace), backend, trace


class MERuntimeContractTests(unittest.TestCase):
    def test_memory_rom_ram_and_snapshot(self):
        runtime, _, _ = make_runtime()
        runtime.state.memory.write(0x1000, b"XY")
        snap = runtime.snapshot()
        with self.assertRaises(ContractError):
            runtime.state.memory.write(0x0000, b"X")
        runtime.state.memory.write(0x1000, b"ZZ")
        runtime.restore(snap)
        self.assertEqual(runtime.state.memory.read(0x1000, 2), b"XY")

    def test_step_is_bounded_and_traceable(self):
        runtime, backend, trace = make_runtime()
        result = runtime.step(3)
        self.assertEqual(result.instructions, 3)
        self.assertEqual(runtime.state.registers.get("pc"), 0x103)
        self.assertEqual(backend.count, 1)
        self.assertEqual([event.kind for event in trace.events], ["step_begin", "step_end"])

    def test_syscall_and_mmio_boundaries(self):
        runtime, _, _ = make_runtime()
        runtime.state.syscalls.register(7, lambda request: SyscallResult(request.arguments[0] + 1))
        self.assertEqual(runtime.state.syscalls.dispatch(SyscallRequest(7, (4,))).return_value, 5)
        self.assertEqual(runtime.state.syscalls.dispatch(SyscallRequest(8)).status, "unsupported")
        runtime.state.mmio.write(0xF000, 4, 0x55)
        self.assertEqual(runtime.state.mmio.read(0xF000, 4), 0x55)

    def test_interrupts_and_reset_restore_initial_state(self):
        runtime, backend, _ = make_runtime()
        runtime.state.interrupts.raise_interrupt(Interrupt(3, b"x"))
        runtime.step()
        runtime.reset()
        self.assertEqual(runtime.state.registers.get("pc"), 0x100)
        self.assertEqual(runtime.state.interrupts.pending(), ())
        self.assertEqual(runtime.step_index, 0)
        self.assertEqual(backend.count, 0)

    def test_restore_replays_the_same_next_step(self):
        runtime, _, _ = make_runtime()
        snapshot = runtime.snapshot()
        first = runtime.step(2)
        first_pc = runtime.state.registers.get("pc")
        runtime.restore(snapshot)
        second = runtime.step(2)
        self.assertEqual(first, second)
        self.assertEqual(runtime.state.registers.get("pc"), first_pc)


if __name__ == "__main__":
    unittest.main()

