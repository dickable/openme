# Synthetic Unicorn-to-MEI lab

`tools/run_unicorn_mei_lab.py` is a user-facing runner for the existing
`csme/mei/unicorn_mei_bridge.py`. It sends one synthetic opcode and one
synthetic payload through the small 32-bit Unicorn program, the project-defined
MEI/HBM transport model, and back to a response mailbox.

The lab is deliberately bounded:

- The only inputs are `--opcode` and `--payload-hex` command-line values.
- It never reads firmware files or loads a firmware image.
- It never opens hardware devices and never uses a network connection.
- Its JSON contains no timestamps, random values, host paths, or other
  run-dependent fields, so the same inputs produce the same output.

## Run it

From the repository root, in an MSYS2 UCRT64 terminal:

```bash
/ucrt64/bin/python.exe tools/run_unicorn_mei_lab.py \
  --opcode 0x20 \
  --payload-hex 68656c6c6f
```

The equivalent Windows command is:

```powershell
C:\msys64\ucrt64\bin\python.exe tools/run_unicorn_mei_lab.py --opcode 0x20 --payload-hex 68656c6c6f
```

The example uses opcode `0x20` and the hexadecimal spelling of `hello`. The
runner also has these same values as defaults, so the shorter command below is
equivalent:

```bash
/ucrt64/bin/python.exe tools/run_unicorn_mei_lab.py
```

The command prints one indented JSON document containing the normalized input,
completion, response mailbox, bridge events, CPU instruction/memory traces,
registers, and final transport counters. Payloads are bounded by the model's
synthetic message size; an oversized payload is reported as an error.

## Test it

Use the installed UCRT64 Python from the repository root:

```bash
/ucrt64/bin/python.exe -m unittest tools/test_run_unicorn_mei_lab.py -v
```

The tests check deterministic repeated runs, JSON output, empty payloads, and
input validation. The bridge's own focused tests remain available with:

```bash
/ucrt64/bin/python.exe -m unittest -v csme.tests.test_unicorn_mei_bridge
```
