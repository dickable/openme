# T460 Read-Only Physical Validation Checklist

This checklist is for identifying and reading a Lenovo ThinkPad T460-class platform without modifying firmware. It is a preparation and evidence-gathering procedure only.

## Non-negotiable boundaries

- [ ] Use a legally obtained, sacrificial test machine that is not used for daily work.
- [ ] Do not write to, erase, unlock, reflash, or otherwise modify any firmware device.
- [ ] Do not boot or test an experimental firmware image on physical hardware.
- [ ] Do not bypass signatures, platform authentication, Boot Guard, descriptor protections, or other security controls.
- [ ] Stop if a step requires guessing a pin, voltage, chip identity, or recovery procedure.
- [ ] Keep the machine powered off and disconnected from external power when opening it, except where a documented read-only procedure explicitly requires otherwise.
- [ ] Record observations and photographs without publishing private identifiers or firmware bytes.

## 1. Identify the exact platform

- [ ] Record the complete model and machine type from the chassis label, BIOS information screen, and service documentation.
- [ ] Confirm whether the machine type is 20FM or another T460 variant; do not infer the variant from the family name alone.
- [ ] Record the serial number privately, but do not put it in the repository.
- [ ] Record CPU model, installed memory, display configuration, docking features, and whether the system is vPro or non-vPro.
- [ ] Photograph the motherboard identification markings and board revision.
- [ ] Confirm the motherboard identifier against reliable Lenovo service documentation.
- [ ] Record the currently installed BIOS revision and ME/CSME version only as observed metadata; do not download or apply an update.
- [ ] Record whether security features such as Boot Guard are documented or reported by the platform.
- [ ] Treat the supplied filename `Lenovo T460 NM-A581.bin` as a hypothesis until the physical board identity is independently confirmed.

## 2. Identify the SPI devices and electrical requirements

- [ ] Locate every SPI flash package on the motherboard using board documentation and visual inspection.
- [ ] Record each chip manufacturer, exact part number, package, capacity, and marking orientation.
- [ ] Determine the chip’s operating voltage from its datasheet; never assume 3.3 V or 1.8 V.
- [ ] Verify the programmer, socket, clip, adapter, and voltage translator are electrically compatible with the exact chip.
- [ ] Confirm whether the chip is accessible in-circuit or must be removed for a reliable read; do not desolder anything as part of this phase.
- [ ] Identify the separate EC ROM, if present, and keep it distinct from the main SPI image.
- [ ] Record board-level power and ground points needed for safe measurement, without applying programming voltage.
- [ ] Stop if the chip marking is unreadable, duplicated, reballed, or inconsistent with the expected capacity.

## 3. Identify read-only connection points

- [ ] Obtain a boardview, schematic, service manual, or other legally obtained documentation before probing.
- [ ] Identify the SPI pins by documented signal name: chip select, clock, input, output, and ground.
- [ ] Identify documented test pads or recovery points and photograph them before connecting anything.
- [ ] Verify pin 1 orientation and continuity to the intended chip pins with the machine unpowered.
- [ ] Check for shorts between power and ground before attaching any clip or adapter.
- [ ] Confirm that the external programmer can be placed in a read-only workflow or otherwise has no write operation enabled.
- [ ] Do not probe undocumented pads by trial and error.
- [ ] Do not connect a programmer while the board is powered unless the documented procedure explicitly requires it and the electrical risks have been reviewed.

## 4. Prepare the external programmer

- [ ] Obtain an external SPI programmer before any physical firmware work.
- [ ] Record the programmer model, software version, adapter model, voltage setting, and configuration.
- [ ] Verify the programmer supports the exact SPI chip and capacity.
- [ ] Verify the programmer’s voltage output with appropriate test equipment before connecting it to the board.
- [ ] Disable or avoid all write, erase, chip-ID programming, lock-bit, and verification actions.
- [ ] Prepare a clean, isolated analysis computer and a known-good storage location for read results.
- [ ] Keep the programmer disconnected until the board identity, chip identity, voltage, and pin mapping are documented.

## 5. Capture two independent full reads

- [ ] Remove the battery and external power according to the manufacturer’s service procedure.
- [ ] Make the first full-chip read using the documented read-only setup.
- [ ] Save the result as an immutable original, for example `t460-read-01.bin`.
- [ ] Disconnect and reconnect the read setup, or otherwise establish an independent capture path.
- [ ] Make a second full-chip read and save it separately, for example `t460-read-02.bin`.
- [ ] Confirm both reads have the exact expected chip capacity; do not accept a partial or truncated read.
- [ ] Do not repair, pad, concatenate, normalize, or edit either original read.
- [ ] If the reads differ, stop and diagnose the connection, power, chip selection, and electrical setup before any further interpretation.

## 6. Hash and preserve the originals

- [ ] Calculate SHA-256 hashes for both full-chip reads.
- [ ] Record file size, timestamp, programmer identity, chip identity, and hash in a separate metadata record.
- [ ] Store the two original reads in separate write-protected or otherwise controlled locations.
- [ ] Create at least one additional backup without changing the original bytes.
- [ ] Keep private machine identifiers and photographs outside the public repository.
- [ ] Add only hashes and non-sensitive structural metadata to OpenME unless publication of the binary is explicitly reviewed and authorized.
- [ ] Verify that the repository ignore rules exclude all firmware binaries, EC dumps, and temporary read files.

## 7. Compare the reads and inspect structure

- [ ] Confirm the two SHA-256 hashes match exactly.
- [ ] Confirm byte-for-byte equality with a binary comparison tool.
- [ ] Parse the flash descriptor from a copy or read-only view of the image.
- [ ] Record descriptor location, region boundaries, and region sizes.
- [ ] Record BIOS, ME/CSME, GbE, and any platform-data regions without extracting or modifying their contents.
- [ ] Compare the physical dump’s region layout with the existing metadata from the supplied 16 MiB image.
- [ ] Treat a layout mismatch as evidence that the images may come from different hardware or firmware generations.
- [ ] Preserve all mismatching reads for diagnosis; do not discard a read because it is inconvenient.

## 8. Review descriptor permissions

- [ ] Read and record descriptor permission fields using a metadata-only parser.
- [ ] Identify which regions are marked readable, writable, or inaccessible to each documented controller.
- [ ] Treat permission bits as evidence, not as authorization to change them.
- [ ] Do not attempt to unlock, reconfigure, override, or bypass descriptor protections.
- [ ] Do not test writes even if the descriptor appears writable.
- [ ] Record uncertainty where the permission interpretation depends on undocumented or platform-specific behavior.

## 9. Recovery planning before any future experiment

- [ ] Obtain and validate an external SPI programmer before considering any future modification.
- [ ] Confirm that the programmer can read the exact chip independently of the laptop’s normal boot path.
- [ ] Maintain at least two verified original full-chip dumps before any modification is even discussed.
- [ ] Document how the chip would be restored using the programmer, without performing that operation now.
- [ ] Identify a second recovery route if available, such as a verified spare chip or documented service procedure.
- [ ] Define a stop condition for failed reads, unexpected identity, mismatched hashes, or uncertain voltage.
- [ ] Use a sacrificial test machine and never a daily-use laptop.
- [ ] Require a separate review and explicit authorization before any future write operation.
- [ ] Keep this phase read-only; no flashing, erasing, patching, or experimental booting is authorized by this checklist.

## Evidence record template

Record the following in a private lab notebook or local metadata file:

```text
Machine type:
Board identifier/revision:
CPU:
vPro status:
BIOS revision observed:
ME/CSME revision observed:
SPI chip manufacturer/part number:
SPI capacity:
SPI voltage:
Programmer and adapter:
Read 1 filename and SHA-256:
Read 2 filename and SHA-256:
Byte-for-byte comparison:
Descriptor region summary:
Descriptor permissions summary:
Recovery method validated:
Open questions:
```

Completion of this checklist establishes a trustworthy, read-only hardware baseline. It does not authorize firmware modification or flashing.
