# OpenME PCI/MMIO contract v0

This is a project-defined contract implemented by the local native QEMU
prototype. It is not an Intel device definition and must not use Intel vendor
or device identifiers.

## PCI identity

- Vendor ID: `0x1234` (test-only project identity)
- Device ID: `0x4D45` (test-only project identity)
- No DMA in version 0.
- One small MMIO BAR.
- Interrupt behavior is represented by `STATUS_IRQ_PENDING`; native QEMU integration may initially use INTx.

## MMIO registers

| Offset | Name | Access | Meaning |
|---:|---|---|---|
| `0x00` | STATUS | read | Ready, interrupt-pending, and suspended bits |
| `0x04` | CONTROL | write | Reset and interrupt acknowledgement bits |
| `0x08` | VERSION | read | Model version `0x00010000` |
| `0x0C` | EVENT | read | Monotonic model event number |
| `0x10` | RX_LENGTH | read | Payload length of the oldest queued response |
| `0x14` | DOORBELL | write | Project-defined command number |
| `0x18` | TX_LENGTH | read/write | Length of the bounded transmit payload |
| `0x20` | TX_DATA | read/write | Bounded transmit window, up to 272 bytes (frame header plus payload) |
| `0x120` | RX_DATA | read | Oldest bounded response window, up to 272 bytes |
| `0x220` | RX_POP | write | Remove the oldest queued response |
| `0x228` | ERROR | read | Sticky model-error indicator |

The doorbell command values used by the native shell are `RESET=1`,
`START=2`, `ENUMERATE=3`, `PROPERTIES=4`, `CONNECT=5`, `FLOW_CONTROL=6`,
`DATA=7`, `DISCONNECT=8`, `SUSPEND=9`, and `RESUME=10`.

The current native artifact includes two bounded MMIO paths. The legacy path
echoes up to 256 raw bytes. The framed path accepts one complete v0 frame
(16-byte header plus up to 256-byte payload), rings `CMD_DATA`, then returns a
framed response through `RX_DATA`. The native adapter supports deterministic
`RESET`, `START`, `DATA`, `SUSPEND`, and `RESUME` framing; other valid v0
opcodes return `UNSUPPORTED` until a client schema is added. The response
queue holds eight entries. This extension remains a project-defined test
interface; it is not HECI or an Intel ME protocol.

The native device is instantiated explicitly with the QEMU device name
`openme-me`. It uses the test-only PCI identifiers above and raises a
conventional INTx interrupt while a response is pending. Writing
`CONTROL_ACK_IRQ` clears the interrupt line without removing the bounded
response-count entry; response payload transport is bounded MMIO only. DMA is
intentionally absent.

## Safety and determinism

- No real firmware image is loaded by the shell.
- No network, external service, or hardware access is used.
- All queues are bounded.
- Reset clears pending responses.
- Unknown doorbell commands fail explicitly.
- The model uses project-defined clients and commands only.

