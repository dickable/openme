# Local lab verification

`tools/verify_lab.py` is a local-only smoke test for the synthetic OpenME lab.
It verifies that the optional Unicorn runtime/bridge and the project-defined
QEMU contract modules can be imported, then runs small bounded synthetic
transactions through them.

The utility reports the Python, Unicorn, and contract versions/statuses. It
does not read firmware, inspect the firmware directories, use the network,
access hardware, launch QEMU, or write files. The QEMU checks exercise the
Python contract façades only, including the data-only QEMU launch-plan helper;
they do not validate a native QEMU build or execute a launch plan.

Run it from the repository root:

```powershell
python tools/verify_lab.py
```

For machine-readable output:

```powershell
python tools/verify_lab.py --json
```

Exit status `0` means every check passed. Exit status `1` means verification
failed. In particular, the utility fails clearly when the optional `unicorn`
package is unavailable; it does not install dependencies or silently skip the
Unicorn checks.

The focused tests follow the repository's `unittest` layout:

```powershell
python -m unittest tools.test_verify_lab -v
```

The bounded checks use synthetic instruction bytes and short payloads only.
They are a repeatable development-lab check, not evidence of firmware
compatibility, Intel ME compatibility, hardware readiness, or a successful
QEMU integration.
