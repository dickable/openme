# HECI/MEI emulation requirements

This document defines the research target for an OpenME host-facing Intel Management Engine Interface (MEI), historically called HECI, model. It is written for a Skylake mobile platform with a Lenovo ThinkPad T460-class reference target. It describes the public interface visible to host software; it does not claim to describe the private ME firmware implementation.

The scope is limited to documentation, emulation, and read-only observation. It does not include firmware modification, signature or platform-authentication bypasses, or instructions for flashing a machine.

## Classification used here

- **Documented fact:** supported by a public Intel datasheet or public Linux kernel implementation/documentation.
- **Platform-specific unknown:** must be confirmed for the exact T460 board, PCH SKU, firmware configuration, and ME generation.
- **OpenME design decision:** an explicit choice for a safe, deterministic emulator. It is not evidence of real Intel behavior.

## 1. Platform and PCI identity

### Documented facts

The public 6th Generation Intel Core I/O Platform Datasheet identifies the Sunrise Point mobile PCH functions as follows:

| PCI location | Device ID | Public description |
| --- | ---: | --- |
| `D22:F0` | `9D3A` | Intel MEI #1 |
| `D22:F1` | `9D3B` | Intel MEI #2 |
| `D22:F2` | `9D3C` | IDE Redirection |
| `D22:F3` | `9D3D` | Keyboard and Text Redirection |
| `D22:F4` | `9D3E` | Intel MEI #3 |

The PCI vendor is Intel (`8086`). The device is exposed through normal PCI configuration space and a memory BAR. Linux's MEI driver selects hardware behavior by PCI device ID and a hardware-operations profile; it does not assume that every MEI generation has identical registers or features.

The Intel 100 Series PCH register datasheet lists the MEI function's PCI configuration fields, including the identifier, command/status, revision/class, BAR, interrupt information, host firmware status registers, PCI power-management capability, and MSI-related registers.

### Platform-specific unknowns

The T460 20FM hypothesis does not by itself prove all of the following:

- The exact PCH-U/PCH-Y/Sunrise Point variant.
- Which MEI functions are enabled in the shipped configuration.
- The exact revision ID and subsystem IDs.
- Whether the machine exposes only MEI #1 or additional MEI functions.
- The BAR address assigned at runtime and the implemented BAR size.
- Whether the T460's firmware hides, disables, or changes any function for a particular SKU.

These values must be obtained from read-only PCI enumeration on the exact machine or from an independently verified platform record. The current SPI dump does not prove the complete PCI configuration state.

### OpenME design decisions

OpenME should have two profiles:

1. **OpenME test profile:** retains the current non-Intel test PCI identity so protocol tests cannot accidentally be mistaken for compatibility with a real MEI controller.
2. **Skylake compatibility profile:** optionally exposes the documented `8086:9D3A` identity at `00:16.0`-equivalent topology only after the register model is sufficiently complete for a Linux guest test.

The compatibility profile must be opt-in, clearly labeled, and used only inside the emulator. It is not intended to impersonate a physical device or to bypass host security controls.

## 2. BAR and MMIO register surface

### Documented facts

The public Intel PCH register material and Linux MEI hardware code identify the following primary MEI MMIO registers. The offsets below are relative to the MEI MMIO BAR:

| Offset | Register | Direction / role |
| ---: | --- | --- |
| `0x00` | `H_CB_WW` | Host circular-buffer write window |
| `0x04` | `H_CSR` | Host control/status |
| `0x08` | `ME_CB_RW` | ME circular-buffer read window, host read access |
| `0x0C` | `ME_CSR_HA` | ME control/status, host read access |
| `0x10` | `H_HPG_CSR` | Power-gating/isolation control on supported hardware |
| `0x800` | `H_D0I3C` | D0i3 control on supported hardware |

The Linux implementation treats the circular buffers as arrays of 32-bit slots. It obtains the buffer depth and read/write pointers from control/status fields, writes a message header and payload through the write window, and reads returned slots through the read window. A message may occupy multiple slots and the final slot may contain fewer than four payload bytes.

The relevant host-control fields documented by the Linux hardware header include host buffer depth, host write/read pointers, host reset, host ready, host interrupt generate, host interrupt status, and host interrupt enable. The ME control/status view contains the corresponding ME buffer state plus ME reset/ready/interrupt state as visible to the host.

The PCI configuration space contains firmware-status registers at offsets used by Linux for the MEI hardware family, including `0x40`, `0x48`, `0x60`, `0x64`, `0x68`, and `0x6C`. The exact meaning and reset values are platform-generation-specific; they are not interchangeable with a marketing-version string.

### Platform-specific unknowns

- The exact BAR size and alignment on the T460.
- Reset values of every reserved and status bit.
- Which power-gating and D0i3 registers are active on the exact firmware configuration.
- Whether the platform uses legacy interrupt delivery, MSI, or a combination during different phases.
- Whether later or optional DMA-ring extensions are advertised.
- The exact circular-buffer depth reported by the physical MEI function.

### OpenME design decisions

The first compatibility implementation should model the four core registers at `0x00` through `0x0C`, with the power-management registers returning conservative unsupported behavior until a profile has evidence that they are needed. All reserved bits should read as zero unless a documented guest-driver access requires another value. Writes to unsupported fields should be ignored or logged deterministically, not interpreted as undocumented commands.

The emulator should maintain separate host-to-ME and ME-to-host circular buffers, expose their depth and pointers consistently, and reject writes that exceed available slots. A trace mode should record register accesses, slot counts, message headers, and interrupt transitions without recording private firmware bytes.

## 3. Host bus messages and framing

### Documented facts

Linux represents the host/ME transport with a packed 32-bit MEI message header followed by zero or more 32-bit data slots. The header carries host and ME client addresses, a byte length, completion state, and flags for features such as extended headers and DMA-ring handling. Linux validates the header before consuming the payload and rejects reserved or inconsistent values.

The host bus message (HBM) control channel uses address `0:0`. Client traffic is addressed using a host client address and an ME client address. The Linux source implements an HBM state machine with states corresponding to:

1. Idle.
2. Host start/version exchange.
3. Optional capability setup.
4. Optional DMA-ring setup.
5. Client enumeration.
6. Client-property acquisition.
7. Started/operational.

The Linux implementation sends a host-start request containing the host HBM version. Depending on negotiated support, it can then exchange capabilities, configure DMA rings, enumerate clients, and request properties for each client. The public Linux implementation is therefore a useful executable description of the host-side sequencing, but it is not a complete specification of every firmware response.

Message completion is separate from the byte length. A client message can be fragmented across multiple transport messages; the completion flag indicates that the current client message is complete. The transport must preserve ordering and must not deliver a partial message as a completed client response.

### Platform-specific unknowns

- The HBM version supported by the exact ME firmware in the dump.
- Which optional HBM capabilities are advertised.
- Whether the exact firmware uses DMA rings, extended headers, virtual tags, dynamic clients, or event notifications.
- Timeout values and error behavior for every HBM request.
- Which client addresses are fixed and which are assigned during enumeration.

### OpenME design decisions

OpenME should implement the non-DMA, non-extended-header path first. It should reject optional features explicitly with a documented unsupported result instead of silently pretending to support them. The emulator should support deterministic fragmentation tests even when the initial implementation uses only the normal circular buffers.

## 4. Client GUID enumeration and properties

### Documented facts

ME features are exposed as clients identified by unique GUIDs. The Linux MEI documentation states that each client has its own protocol and that the host connects to a client by GUID through `MEI_CONNECT_CLIENT_IOCTL`. The returned client properties include a protocol version and maximum message length.

At the HBM level, Linux maintains a client map, requests enumeration, then requests properties for each discovered ME client. The properties structure includes the protocol GUID and fields used by the driver for protocol version, maximum message length, and connection limits. Host and ME client addresses are then used for the live connection.

At the user-space level, Linux exposes `/dev/meiX`. An application opens the device, supplies a desired GUID in the connect ioctl, receives the negotiated properties, writes protocol data, reads responses, and closes the session. The MEI driver is transparent to the client payload; it does not define the private protocol carried by a particular GUID.

### Platform-specific unknowns

The current OpenME SPI metadata lists names such as `heci`, `fwupdate`, and `ptt`, but those names do not establish the GUIDs, protocol versions, MTUs, or permissions of the corresponding host clients. The current dump also does not prove that every client present in firmware is exposed through MEI on this particular board.

The exact T460 client table must therefore be treated as unknown until obtained from a compatible physical system through read-only observation or from reliable public documentation.

### OpenME design decisions

The first guest-test client should be an OpenME-owned test GUID with a documented echo or capability protocol. It should be clearly separate from any Intel client GUID. This lets us validate enumeration, properties, connection, fragmentation, and flow control without claiming to implement AMT, PTT, firmware update, or another security-sensitive service.

The emulator should make the client table a profile input:

- UUID/GUID.
- ME address.
- Protocol version.
- MTU.
- Maximum simultaneous connections.
- Fixed-address or dynamically assigned behavior.
- Notification support.
- Optional-feature flags.

## 5. Connect, properties, MTU, and flow control

### Documented facts

The Linux API returns `max_msg_length` as the client MTU. The documented meaning is the maximum data that can be sent or received for that connected client. The MTU is a client property, not a universal MEI bus maximum.

The Linux driver tracks transmit and receive flow-control credits per client. Before client data is sent, the host and ME exchange flow-control messages. The driver refuses or defers traffic when the relevant credit or circular-buffer capacity is unavailable. A single client write may still require multiple transport messages when the payload exceeds the negotiated transport capacity.

Connect and disconnect are HBM transactions addressed to the selected host/ME client pair. Linux maps firmware connection results such as not-found, already-started, out-of-resources, message-too-small, and not-allowed into host-visible errors.

### Platform-specific unknowns

- Exact initial credit counts.
- Whether a given T460 ME client permits more than one connection.
- Whether a client allows virtual tags.
- Client-specific framing, request/response semantics, and notification formats.
- The relationship between a module name in the private firmware CPD and an exposed MEI client.

### OpenME design decisions

The model should enforce MTU and credits rather than treating them as advisory. Tests should cover:

- Exact-MTU payloads.
- One-byte-over-MTU rejection.
- Fragmented messages.
- Zero-credit backpressure.
- Credit replenishment after a read.
- FIFO ordering across multiple clients.
- Disconnect while traffic is pending.

The first model may use a small deterministic credit count, but the value must be visible in traces and never be presented as the T460's real value.

## 6. Interrupts and reset

### Documented facts

Linux enables and disables MEI interrupts through `H_CSR`. It observes interrupt status, uses the host-interrupt-generate bit when submitting work, clears interrupt state, and synchronizes interrupt handling before reset or power transitions. The PCI function also exposes standard interrupt configuration and MSI-related fields in PCI configuration space.

The driver has separate host-ready and ME-ready checks. It waits for the ME side to become ready, releases ME reset, marks the host ready, and then starts HBM. A reset clears HBM state and removes the discovered client list before initialization is repeated.

Malformed headers, circular-buffer overflow, stalled initialization, and connection timeouts can cause the driver to reset the device. A compatibility model must make reset observable and must not leave stale client connections or queued messages across a reset.

### Platform-specific unknowns

- The exact interrupt delivery mode used by a physical T460.
- Reset timing and whether the ME stays powered across host reset, warm reboot, S3, or deeper states.
- Firmware-specific behavior after a malformed or unsupported message.
- Whether any fixed-address clients survive a link reset.

### OpenME design decisions

The initial QEMU implementation should support one interrupt mode at a time, selected by profile, with INTx as the first compatibility target and MSI as a later test target. Reset must clear both circular buffers, HBM state, client connections, credits, notification state, and pending interrupts. Reset behavior should be tested through the Linux driver and through direct MMIO tests.

## 7. Firmware status and boot readiness

### Documented facts

Linux reads ME firmware-status values from PCI configuration space through hardware-specific callbacks. It uses these values for hardware configuration, power-management capability checks, and diagnostics. The source supports multiple status registers, not a single universal version field.

The Skylake PCH documentation also shows that the PCH contains separate SPI, power-management, LPC, GbE, and MEI functions. The MEI controller is therefore one part of a larger boot platform; reproducing its PCI endpoint alone does not reproduce the complete host boot dependency chain.

### Platform-specific unknowns

- Which firmware-status values the T460 BIOS checks during boot.
- Which status bits reflect the exact ME image's state, SKU, or operating mode.
- Whether Boot Guard or other platform security configuration changes the required boot sequence.
- Which services must be ready before the BIOS proceeds.

The current SPI analysis identifies a coherent ME region and metadata structures, but it does not establish the runtime values of the PCI firmware-status registers or the BIOS's exact decision logic.

### OpenME design decisions

The emulator should expose a profile-defined, internally consistent status set and log every host read. It should not synthesize success values intended to defeat a real security check. Any boot-success experiment must use a synthetic guest platform or a deliberately documented test profile.

## 8. Power states and low-power behavior

### Documented facts

The Linux MEI hardware code distinguishes device readiness, reset, power gating, and D0i3-related state. It has explicit operations for entering and leaving power-gating isolation and reads the D0i3 capability/status path when supported. The driver also participates in Linux runtime power management and autosuspend.

The public Intel register material lists PCI power-management capability registers and MEI-specific D0i3 control. This means a guest driver can observe more than simple message transport: it can observe whether the device claims to support power transitions and whether transitions complete.

### Platform-specific unknowns

- The T460's exact D0i3 and power-gating capabilities.
- Required sequencing relative to ACPI S-states, PCI D-states, and PCH reset signals.
- Wake behavior and interrupt delivery from low-power states.
- Which ME clients must be disconnected or quiesced before entering a low-power state.

### OpenME design decisions

Power behavior should be implemented in layers:

1. Keep the device permanently active for baseline protocol tests.
2. Add PCI D-state transitions with deterministic refusal of unsupported transitions.
3. Add HBM power-gating/isolation messages.
4. Add D0i3 only after guest-driver traces demonstrate that it is needed.

No power-state behavior should be inferred from the private firmware CPD alone.

## 9. Guest-driver validation plan

The first real compatibility test is not execution of proprietary ME firmware. It is whether an unmodified Linux MEI driver can discover and operate the emulated host-facing interface.

### Test stages

1. Boot a disposable Linux guest with the OpenME test PCI identity.
2. Confirm PCI configuration reads, BAR assignment, and MMIO bounds.
3. Enable the Linux MEI driver and record whether it creates `/dev/mei0`.
4. Verify the host-ready/ME-ready sequence and HBM start response.
5. Verify client enumeration and properties.
6. Connect to the OpenME-owned test GUID.
7. Exercise MTU boundaries, fragmentation, credits, notifications, disconnect, and reset.
8. Repeat with interrupt delivery enabled and with polling disabled.
9. Exercise suspend/resume only after baseline traffic is stable.
10. Compare the guest trace with Linux driver expectations and classify every mismatch.

### Evidence to collect

- `lspci -nnvv` output for the virtual function.
- PCI config-space reads and writes.
- BAR size and assigned address.
- MMIO access trace.
- HBM state transitions.
- Client GUID/property table.
- Interrupt assertions and clears.
- Reset and power-state transitions.
- Driver error codes and timeout behavior.

The test harness should use synthetic client data and publish only traces and metadata. It must not include the private SPI dump or proprietary ME module bytes.

### Success criteria

The first success milestone is a Linux guest that loads the MEI driver, completes HBM initialization, enumerates the OpenME test client, connects to it, exchanges bounded messages, and recovers cleanly from reset. That establishes host-facing compatibility for the tested subset; it does not establish that OpenME is a replacement for Intel ME or that a physical T460 would boot with it.

## 10. Implementation order

1. Preserve the current non-Intel fake device and its tests.
2. Add a profile object containing PCI identity, BAR size, register capabilities, buffer depth, HBM version, interrupt mode, and client table.
3. Implement the four core MMIO registers and 4-byte circular buffers.
4. Implement host-ready/ME-ready and reset transitions.
5. Implement HBM start, enumeration, properties, connect, disconnect, and flow control.
6. Add a synthetic test GUID and guest-driver test harness.
7. Add firmware-status reads with profile-defined values and trace logging.
8. Add optional interrupts, power gating, and D0i3 one capability at a time.
9. Only after the host-facing model is stable, evaluate whether a Unicorn-backed ME runtime can provide selected service implementations. CPU emulation alone does not supply the ME peripherals, boot state, security boundaries, or platform services.

## Sources

- [Intel 6th Generation Core Processor Families I/O Platform Datasheet, Volume 1](https://cdrdv2-public.intel.com/332995/332995-skl-io-platform-datasheet-vol1_rev004.pdf) — Skylake PCH device/function and MEI device-ID table.
- [Intel 100 Series PCH Datasheet, Volume 2](https://www.intel.com/content/www/us/en/content-details/332691/intel-100-series-chipset-family-platform-controller-hub-pch-datasheet-volume-2.html) — PCH PCI configuration and MEI register reference; the public Intel page links the register datasheet.
- [Linux MEI documentation](https://docs.kernel.org/driver-api/mei/mei.html) — host API, GUID clients, connect ioctl, properties, MTU, and notifications.
- [Linux MEI hardware register definitions](https://raw.githubusercontent.com/torvalds/linux/master/drivers/misc/mei/hw-me-regs.h) — public device IDs, PCI firmware-status offsets, MMIO offsets, buffer-pointer fields, ready/reset/interrupt fields, and D0i3 fields.
- [Linux MEI HBM implementation](https://raw.githubusercontent.com/torvalds/linux/master/drivers/misc/mei/hbm.c) — public host-bus-message sequencing, enumeration, properties, connect/disconnect, and power-management messages.
- [Linux MEI hardware implementation](https://raw.githubusercontent.com/torvalds/linux/master/drivers/misc/mei/hw-me.c) — public circular-buffer, readiness, reset, interrupt, firmware-status, and power-management handling.
- [Linux MEI device structures](https://raw.githubusercontent.com/torvalds/linux/master/drivers/misc/mei/mei_dev.h) — public slot size, device/HBM states, client bookkeeping, credits, and hardware-operation abstractions.

The Linux source is an implementation reference for the host driver, not a guarantee that every behavior is identical across all Intel generations or every T460 firmware configuration.
