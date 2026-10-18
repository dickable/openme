# OpenME console

`tools/openme_console.py` is the user-facing CLI for the deterministic,
software-only research console in `csme/runtime/research_console.py`. It is a
thin input/output boundary around that backend. It does not start QEMU, load
firmware, read firmware files, access a physical device, or use the network.

The backend must expose either a `ResearchConsole` class or a
`create_console()` factory. The resulting object must expose
`execute(line)`, `run_command(line)`, or `handle_command(line)`. The command
line is passed as one normalized string, so the backend remains the source of
truth for model behavior and state transitions.

## Interactive mode

Run the console from the repository root:

```text
python tools/openme_console.py
```

Useful commands include:

```text
help
reset
heci-status
boot
dir /
dir /etc/openme
cat /etc/openme/platform
send 0x2a "hello openme"
trace
suspend
resume
exit
```

Blank lines are ignored. Invalid commands and backend errors are printed as
`error: ...` messages; the session continues so a typo does not terminate an
interactive experiment.

## Deterministic scripts

Use `--script PATH` to run one command per line without prompts:

```text
python tools/openme_console.py --script commands.txt
```

Use `--script -` to read commands from standard input. `exit` or `quit` ends
the script early. Script mode continues after an invalid command, prints the
error, and exits with status `1` after processing the remaining commands. A
missing/unreadable backend or script exits with status `2`.

The script input is the only file the CLI reads. Keep scripts limited to
project-defined model commands; the CLI has no option for a firmware path,
QEMU executable, device path, network endpoint, or hardware operation.

## Tests

Run the CLI tests from the repository root:

```text
python -m unittest tools.test_openme_console -v
```

The tests inject an in-memory backend double. They do not load firmware,
start QEMU, access hardware, or use a network.

`boot` starts the project-authored synthetic runtime environment. It walks a
deterministic boot sequence, installs a synthetic memory map and services, and
exposes an in-memory MFS-like tree. `dir` and `cat` operate on that tree only;
they do not read the SPI dump or any host filesystem. The tree is intentionally
not Intel ME storage and the boot sequence performs no cryptographic check.
