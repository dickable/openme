# Synthetic Unicorn-to-MEI bridge

`csme/mei/unicorn_mei_bridge.py` connects two deliberately limited OpenME
components:

- `unicorn_runtime.py`, an optional 32-bit x86 Unicorn sandbox;
- `mei_hbm.py`, a project-defined host/ME circular-buffer and completion model.

The bridge uses a synthetic request mailbox at `0x2100`, a synthetic response
mailbox at `0x2200`, and a synthetic doorbell at `0x2ff0`. A tiny hand-written
x86 program copies the request opcode to the doorbell. The Unicorn memory trace
listener observes that write, submits the request to the MEI/HBM model, and
writes the deterministic completion back to the response mailbox before the CPU
reads it.

This is an integration test seam, not Intel HECI compatibility. The model uses
project-defined addresses and behavior, does not load firmware, does not use
Intel PCI identifiers, and does not access hardware. It is intended to make
the CPU/runtime, transport, trace, reset, and replay boundaries testable before
any attempt to model additional public platform behavior.

Run the focused test with:

```powershell
python -m unittest -v csme.tests.test_unicorn_mei_bridge
```

The next fidelity increments should be evidence-driven: explicit MMIO access
semantics, interrupt delivery, bounded DMA abstractions, and replayable traces.
They must remain isolated from proprietary firmware execution and security
feature bypasses.
