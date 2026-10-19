# CSME tests

This folder contains regression tests for the CSME boot scaffold, fake devices,
MEI/HBM models, runtime contracts, and CPU sandbox.

Run `python -m unittest discover -s . -p 'test*.py'` from the repository root.
Also run `python -m unittest discover -s tools -p 'test*.py'` for the standalone
tool tests (the `tools` directory is not an ordinary Python package).

`test_source_firmware.py` compiles and runs the C harnesses when GCC is
available, and checks the Multiboot image contract. `test_openme_core.c` tests
state transitions, maximum payloads, malformed requests, and buffer canaries.
`test_flash_workflow.py` mocks every chip operation: passing it is not a
physical programmer test. Run `tools/launch-openme.ps1 -Test` separately for
the real QEMU CPU/serial integration test of the source-built firmware.

`test_openme_persistence.c` covers NOR snapshots, saved counter restoration,
and failure/CRC/overflow paths. `tools/test_run_persist.py` covers the bounded
snapshot transport and host-file commit. Run `python tools/run_persist.py`
separately for the two-process QEMU cold-restart test; see
[the verified report](../../docs/cold-persistence.md).
