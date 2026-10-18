# OpenME synthetic QEMU lab

This lab is a runnable plan for the patched OpenME QEMU PCI shell. It covers
the project-defined device contract only; it is not a recipe for running
Intel ME/CSME firmware or for reproducing a physical platform.

## Safety boundary

The lab is intentionally synthetic and deterministic:

- PCI identity is the explicit test-only value `0x1234:0x4D45`.
- The QEMU device name is `openme-me`, at PCI address `01.0` on `q35`.
- The launch shape uses `-nodefaults`, hidden display, and `-net none`.
- No firmware path or firmware-loading option is part of the contract.
- No network device, host hardware, DMA, external service, or physical PCI
  device is part of the contract.
- The device exposes bounded MMIO queues and project-defined test messages;
  it is not an Intel device, MEI/HECI implementation, or security service.

The helper in `csme/fake_devices/qemu_lab_contract.py` only returns argument tuples
and an environment mapping. Importing it and running its tests do not start
QEMU, QTest, or any other external process.

## Launch contract

The direct-QEMU command shape is:

```text
qemu-system-x86_64 \
  -machine q35 \
  -nodefaults \
  -display none \
  -net none \
  -device openme-me,addr=01.0
```

This is a contract description, not a command run by the repository tests.
The helper constructs the same argv without invoking it:

```python
from qemu_lab_contract import build_qemu_argv

argv = build_qemu_argv("build/qemu-system-x86_64")
```

The helper does not accept arbitrary extra QEMU arguments. In particular, a
firmware image, disk image, kernel, network backend, or hardware passthrough
cannot be added through this contract.

## QTest invocation plan

Apply `csme/qemu/openme-qemu.patch` to a clean QEMU checkout and build the
`x86_64-softmmu` target according to
[`openme-qemu-apply.md`](../qemu/openme-qemu-apply.md). The patched test
is the preferred regression path because it checks the device internally with
QTest and does not require a guest firmware image.

From the QEMU `build` directory, the planned invocation is:

```powershell
$env:QTEST_QEMU_BINARY = ".\qemu-system-x86_64.exe"
.\tests\qtest\openme-pci-test.exe --tap -p /openme/mmio-contract
```

On a Unix-like shell, the equivalent environment setup is:

```bash
QTEST_QEMU_BINARY=./qemu-system-x86_64 \
  ./tests/qtest/openme-pci-test --tap -p /openme/mmio-contract
```

The QTest source in the patch starts QEMU with `-machine q35 -nodefaults
-display none` and adds only `-device openme-me,addr=01.0`. Because default
devices are disabled and no network option is supplied, the QTest guest has
no network device. The test does not load firmware or access host hardware.

The Python representation of that plan is:

```python
from qemu_lab_contract import build_qtest_plan

plan = build_qtest_plan(
    qemu_binary="build/qemu-system-x86_64",
    qtest_binary="build/tests/qtest/openme-pci-test",
)
print(plan.argv())
print(plan.environment())
```

The focused test path `/openme/mmio-contract` covers PCI discovery, the
project test identifiers, the version register, reset, `START`, bounded raw
and framed data, response popping, event counting, suspend, and interrupt
acknowledgement. It does not make the model compatible with Intel firmware.

## Local checks

The data-only helper tests can be run from the repository root without QEMU:

```powershell
python -m unittest -v csme.tests.test_qemu_lab_contract
```

Those tests verify the exact command shape, the explicit non-Intel identity,
the absence of firmware and network inputs, and the focused QTest selector.
