# OpenME bounded payload transport v0

This document defines the first bounded payload transport for the OpenME fake-ME
model. It is a project-defined test interface. It is not Intel HECI/MEI, does
not describe Intel firmware, and must not be used to make compatibility or
replacement claims about Intel ME/CSME.

The transport is intentionally software-only, deterministic, and bounded. It
uses copied frames and explicit service steps. It has no DMA, interrupts, wall
clock, randomness, firmware loading, hardware access, or security-bypass
behavior.

The Python reference implementation is `csme/fake_devices/framed_transport.py`.
`QueuedFramedTransport` implements the bounded submit/service/pop lifecycle;
`FramedTransport` remains available as a direct one-request adapter for simple
tests.

## Transport limits

The limits below are normative for v0:

| Item | Limit |
| --- | ---: |
| Header size | 16 bytes |
| Maximum payload | 256 bytes |
| Maximum frame | 272 bytes (16-byte header + 256-byte payload) |
| Host-to-model queue | 8 accepted request frames |
| Model-to-host queue | 8 response frames |
| Processing unit | 1 request per explicit service step |

There is no fragmentation, continuation flag, scatter/gather list, pointer,
physical address, or variable-sized allocation in the contract. A sender must
fit a complete frame in one bounded submission.

## Frame layout

Every integer is little-endian. The header is exactly 16 bytes and is followed
immediately by `payload_len` bytes. Bytes after the payload are not part of the
frame and must not be consumed.

| Offset | Size | Field | Request rule | Response rule |
| ---: | ---: | --- | --- | --- |
| 0 | 2 | magic | `0x4F4D` (`4D 4F` on the wire) | same |
| 2 | 1 | version | `0x01` | `0x01` |
| 3 | 1 | flags | `0x00` | `0x01` = response, optionally `0x02` = error |
| 4 | 1 | opcode | command identifier | echoed command identifier |
| 5 | 1 | status | `0x00` | result status |
| 6 | 2 | reserved | must be zero | must be zero |
| 8 | 4 | sequence | non-zero host-chosen identifier | copied from request |
| 12 | 2 | payload_len | `0..256` | `0..256` |
| 14 | 2 | reserved | must be zero | must be zero |

The frame length must equal `16 + payload_len` exactly. Sequence values are
opaque to the model. A sender must not reuse a sequence value while its
response is outstanding; after `0xFFFFFFFF`, it wraps to `1`.

## Opcodes

These values correspond to the command names in `host-model-v0.md`:

| Value | Name |
| ---: | --- |
| `0x01` | `RESET` |
| `0x02` | `START` |
| `0x03` | `ENUMERATE` |
| `0x04` | `PROPERTIES` |
| `0x05` | `CONNECT` |
| `0x06` | `FLOW_CONTROL` |
| `0x07` | `DATA` |
| `0x08` | `DISCONNECT` |
| `0x09` | `SUSPEND` |
| `0x0A` | `RESUME` |

Unknown opcode values are validly framed requests and receive an
`UNKNOWN_OPCODE` response.

## Payload rules

Payload bytes are opaque to the transport and are copied without transformation.
Command-specific schemas remain in the host-model note. The v0 fake client
limits are still enforced by the model:

- `openme.control`: maximum application payload 64 bytes.
- `openme.echo`: maximum application payload 256 bytes; `DATA` returns the
  payload unchanged.

The transport maximum is 256 bytes even when a command-specific limit is
smaller. A request that exceeds the negotiated client limit receives
`MESSAGE_TOO_LARGE` and does not alter application state.

## Submission and service semantics

1. The host constructs one complete frame in a local buffer.
2. The model validates the frame length and reserves one response-queue slot.
3. If validation and reservation succeed, the request is copied into the
   host-to-model queue. The original host buffer may then be changed or freed.
4. One explicit service step removes the oldest request, applies its command,
   and appends exactly one response to the model-to-host queue.
5. The host reads and removes responses in FIFO order. A response is matched
   using its echoed sequence value.

An accepted request always produces exactly one response, including an error
response. A rejected submission is not an accepted request and produces no
response; the transport status and counters describe the rejection.

## Queue overflow

The model-to-host queue has capacity for eight complete response frames. The
model must reserve a response slot before accepting a request. Therefore a
full response queue causes the new submission to be rejected atomically with
`QUEUE_FULL`; it must not change protocol state.

If the host-to-model queue is full, submission is likewise rejected atomically
with `QUEUE_FULL`. The model increments a monotonically increasing
`overflow_count` for each rejected submission, saturating at `0xFFFFFFFF`.

Queue-full rejection is observable through the transport status and does not
attempt to enqueue an additional error frame, since doing so could itself
overflow the response queue. Tests must treat the absence of a response for a
rejected submission as expected behavior.

## Reset and status behavior

`RESET` is an in-band command. When its request is accepted, it clears the
active client, suspend state, pending application data, and both queues after
the reset response has been reserved. It returns the lifecycle state to
`READY`, then emits one `OK` response for the reset request. The reset response
is the only response retained from before the reset operation.

Malformed frames that contain a complete 16-byte header are accepted for
processing when a response slot is available and produce one error response.
Frames shorter than 16 bytes, frames whose declared length is unavailable, and
queue-full submissions are rejected before acceptance and produce no response.

Status values are:

| Value | Name | Meaning |
| ---: | --- | --- |
| `0x00` | `OK` | command completed |
| `0x01` | `BAD_MAGIC` | magic is not `0x4F4D` |
| `0x02` | `BAD_VERSION` | version is not `0x01` |
| `0x03` | `BAD_FLAGS` | flags are not valid for the frame direction |
| `0x04` | `BAD_LENGTH` | frame length or reserved fields are invalid |
| `0x05` | `UNKNOWN_OPCODE` | opcode is not defined in v0 |
| `0x06` | `NOT_READY` | command requires `START` first |
| `0x07` | `INVALID_STATE` | command is invalid in the current state |
| `0x08` | `UNKNOWN_CLIENT` | requested client is not registered |
| `0x09` | `MESSAGE_TOO_LARGE` | command/client limit was exceeded |
| `0x0A` | `QUEUE_FULL` | submission was rejected before acceptance |
| `0x0B` | `MALFORMED_PAYLOAD` | command payload schema is invalid |
| `0x0C` | `UNSUPPORTED` | valid shape, unsupported optional behavior |

An error response sets the response flag and the error flag (`flags = 0x03`).
Its opcode and sequence equal the request, and its payload is empty unless a
future command explicitly defines an error payload.

## Test vectors

The following vectors use the exact wire bytes, shown as space-separated
hexadecimal octets. Responses use response flag `01` and status `00` unless
noted otherwise.

### RESET, sequence 1

Request:

```text
4D 4F 01 00 01 00 00 00 01 00 00 00 00 00 00 00
```

Expected response:

```text
4D 4F 01 01 01 00 00 00 01 00 00 00 00 00 00 00
```

### START, sequence 2

Request:

```text
4D 4F 01 00 02 00 00 00 02 00 00 00 00 00 00 00
```

Expected response:

```text
4D 4F 01 01 02 00 00 00 02 00 00 00 00 00 00 00
```

### DATA echo, sequence 4

The payload is the 12-byte ASCII string `hello-openme`.

Request:

```text
4D 4F 01 00 07 00 00 00 04 00 00 00 0C 00 00 00 68 65 6C 6C 6F 2D 6F 70 65 6E 6D 65
```

Expected response:

```text
4D 4F 01 01 07 00 00 00 04 00 00 00 0C 00 00 00 68 65 6C 6C 6F 2D 6F 70 65 6E 6D 65
```

### Unknown opcode, sequence 5

Requesting opcode `0x7F` is validly framed but unsupported:

```text
4D 4F 01 00 7F 00 00 00 05 00 00 00 00 00 00 00
```

Expected error response (`status = 0x05`, `flags = 0x03`):

```text
4D 4F 01 03 7F 05 00 00 05 00 00 00 00 00 00 00
```

### Oversized payload, sequence 6

A frame declaring `payload_len = 257` (`01 01`) is rejected with
`MESSAGE_TOO_LARGE`. The test vector consists of the following 16-byte header
followed by exactly 257 payload bytes (for example, all zeroes):

```text
4D 4F 01 00 07 00 00 00 06 00 00 00 01 01 00 00
```

Expected error response:

```text
4D 4F 01 03 07 09 00 00 06 00 00 00 00 00 00 00
```

### Queue overflow

Submit nine valid requests without service steps and with the response queue
already reserved to capacity. The first eight are accepted in FIFO order. The
ninth is rejected atomically with transport status `QUEUE_FULL`, increments
`overflow_count` by one, changes no protocol state, and produces no response.

## Scope boundary

This contract is only a reproducible interface for OpenME software models and
QEMU experiments. It does not emulate Intel ME internals, prove hardware
compatibility, authorize firmware modification, bypass authentication or
signature checks, or imply that a universal Skylake implementation is feasible.
