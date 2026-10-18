# OpenME host model protocol v0

This is a project-defined deterministic test protocol. It must not be presented as an implementation of Intel’s private ME protocol.

## Commands

`RESET`, `START`, `ENUMERATE`, `PROPERTIES`, `CONNECT`, `FLOW_CONTROL`, `DATA`, `DISCONNECT`, `SUSPEND`, and `RESUME`.

## Test clients

- `openme.control`: protocol 1, maximum message size 64 bytes.
- `openme.echo`: protocol 1, maximum message size 256 bytes. `DATA` returns the payload unchanged.

## Required behavior

- Every request produces exactly one response.
- Unsupported commands and clients return explicit error statuses.
- Payloads above the negotiated limit return `message-too-large`.
- Reset clears the connected client and returns the model to `READY`.
- Trace event numbers are monotonic and deterministic.
- No wall-clock time, randomness, DMA, firmware blobs, or external services are used.

