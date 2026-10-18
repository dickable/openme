# Project-defined MEI trace vectors

`tools/mei_trace_vectors.py` generates and validates a small deterministic JSON
vector set for the OpenME host-facing model. The vectors are intentionally
independent of Unicorn, QEMU, firmware images, and physical hardware.

## Important boundary

These are OpenME project-defined test scenarios. They are **not Intel wire
traces**, HECI captures, ME firmware observations, or claims about undocumented
Intel behavior. The names are convenient labels for the model's state machine.

The vectors contain no firmware bytes and are safe to publish as test fixtures.

## Schema

The document format is `openme-mei-trace-vectors-v0`, using the schema
`openme-project-defined-mei-vector-v0`.

Each document contains seven canonical vectors:

| Vector | Meaning in this project |
| --- | --- |
| `reset` | Host requests a clean model reset |
| `ready` | Model reports readiness |
| `host-to-me` | Host submits a bounded test message |
| `me-to-host` | Model returns a deterministic response |
| `interrupt` | Model signals response availability |
| `queue-full` | A bounded queue rejects an additional message |
| `suspend-resume` | Model enters suspend and returns to ready |

Each event has a sequence number, project-defined kind, actor (`host` or `me`),
state, and a kind-specific `details` object. Payloads are represented only as
lowercase hexadecimal test data.

## Usage

Generate the canonical document to standard output:

```text
python tools/mei_trace_vectors.py generate
```

Write it to a file:

```text
python tools/mei_trace_vectors.py generate --output vectors.json
```

Validate a document:

```text
python tools/mei_trace_vectors.py validate vectors.json
```

Validation checks the format and schema identifiers, canonical vector order,
event sequencing, allowed event kinds, required fields, even-length hex
payloads, queue capacity/depth consistency, and suspend/resume ordering.

The tool does not read firmware, contact external services, execute a guest, or
make claims about Intel's private protocol behavior.
