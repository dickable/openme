# Firmware-Signing Observation Boundary

## Purpose

This note defines what OpenME may safely observe about Intel firmware authenticity and what is outside the project’s scope. It is a research boundary, not a recipe for reproducing, defeating, or replacing Intel’s trust mechanisms.

The project may analyze legally obtained firmware images and public documentation in read-only workflows. It must preserve original artifacts, record hashes, and clearly separate observed facts from interpretations.

## Safe observations

### SPI descriptor and region metadata

Read-only inspection may record:

- The SPI flash descriptor signature and version fields.
- Region base and limit values.
- BIOS, ME/CSME, GbE, PDR, and other region boundaries when declared by the descriptor.
- Access-permission fields, while treating their meaning as platform- and documentation-dependent.
- Hashes, sizes, offsets, and consistency checks for each declared region.

These facts describe the image layout. They do not prove that a region is authentic or that the platform will accept it.

### ME/FPT metadata

Read-only inspection may record:

- The location and structure of an `$FPT` table.
- Partition names, offsets, lengths, flags, and hashes calculated locally.
- Empty or reserved partition slots.
- Manifest or version-like fields, provided undocumented fields are labeled as such.

Locally calculated hashes are integrity fingerprints for the file being examined. They are not proof that Intel, Lenovo, or the platform signed the contents.

### CPD and module boundaries

Read-only inspection may record:

- The location of a `$CPD/` directory.
- Manifest names and identifiers.
- Entry offsets and lengths when they are bounded by the directory and containing partition.
- The relationship between a directory entry and its associated metadata entry.
- Candidate signed-module boundaries when a public format description or an unambiguous local manifest identifies them.

The presence of a CPD entry, a `.met` entry, or a range that looks like a module does not by itself establish that the range is signed. The project must not assign cryptographic meaning to undocumented fields merely because they resemble offsets, versions, or hashes.

### Certificate and key identifiers

OpenME may record certificate subjects, issuers, serial numbers, key identifiers, algorithm identifiers, public-key hashes, or trust-anchor identifiers only when they are already exposed by:

- Lawful public documentation.
- A public specification or vendor-published example.
- Local metadata that is plainly present in the permitted artifact and can be reported without recovering secrets.

Only public identifiers may be recorded. Private keys, key material, extracted secrets, secure-boot databases obtained through unauthorized access, and any recovered signing credentials are out of scope and must not be collected or stored.

## Trust-chain stages

The exact Intel implementation is platform-specific and may not be fully documented for a given Skylake system. OpenME may model a hypothesis as a sequence of stages, but must label each stage by evidence level:

1. **Root or hardware trust anchor** — a processor, PCH, boot-ROM, fused key hash, or other platform-protected starting point described by authoritative documentation or directly observable status.
2. **Platform firmware authentication** — validation of a boot-critical firmware container or manifest before execution or release of the next stage.
3. **ME/CSME partition or module authentication** — validation of partition, manifest, or module contents before loading them.
4. **Runtime update or service authentication** — validation of later-loaded components, applications, or update packages.
5. **Host-facing readiness** — the point at which the ME exposes the expected interface and reports firmware status to the host.

These stages are a research model, not a claim that every platform uses exactly this sequence. A metadata parser can show that a container or boundary exists; it cannot establish when or how a hardware verifier checks it.

## Evidence required to validate a hypothesis

A signing or trust-chain hypothesis should not be treated as validated until independent evidence supports it. Useful evidence may include:

- A public Intel or platform-vendor specification describing the relevant format or verification stage.
- A reproducible parser result showing a stable manifest, boundary, or certificate identifier across independently obtained lawful images.
- A cryptographic verification result using a publicly documented algorithm, public key, and precisely defined signed byte range.
- A documented, read-only platform status or boot log that distinguishes accepted, rejected, and unavailable firmware states.
- Controlled comparisons of unmodified images where only one documented input changes and the resulting metadata or status change is repeatable.
- Independent reproduction by another researcher using the same public inputs and procedure.

Evidence that is not sufficient on its own includes:

- A filename, marketing version string, or `$MN2`-like field.
- A successful local hash calculation without a trusted reference.
- A CPD entry or `.met` file with no documented signature semantics.
- A system booting an image when the relevant verification stage is unknown.
- A failed boot without a captured, attributable authentication status.

## Explicit prohibitions

OpenME must not:

- Bypass, disable, patch around, or weaken signature verification.
- Extract, derive, guess, or publish private signing keys or other secret authentication material.
- Forge certificates, manifests, signatures, hashes, or authenticated images.
- Modify a firmware image and attempt to execute it on hardware as a way to test acceptance.
- Provide instructions for defeating Boot Guard, platform authentication, anti-rollback, or related protections.
- Flash experimental firmware during the initial research phase.
- Treat an emulator’s acceptance of an image as proof that real hardware would accept it.

The safe software path is to parse metadata, model documented interfaces, use synthetic test images for parser tests, and keep any emulator deterministic and isolated. If a future experiment requires a modified image, it must stop at an offline format-level test unless the project has an independently verified recovery path and a separately reviewed authorization and safety plan.

## Current OpenME application

The current T460-class research artifact supports read-only observations of SPI regions, ME/FPT partitions, and FTPR/CPD metadata. The project should report these as metadata findings, not as proof of authenticity. The dump’s board identity, exact marketed CSME version, certificate chain, Boot Guard configuration, and acceptance behavior remain unproven unless separately evidenced.

The project’s existing metadata reports and parser output are appropriate evidence for layout and boundary claims. They are not a substitute for a vendor-documented signature verification procedure or a validated public-key chain.

## Sources

Public sources consulted:

- [Intel, Introduction to Key Usage in Integrated Firmware Images](https://www.intel.com/content/www/us/en/developer/articles/technical/software-security-guidance/resources/key-usage-in-integrated-firmware-images.html) — describes Boot Guard as a hardware chain of trust and discusses public key-hash trust anchors and firmware authentication stages.
- [UEFI Specification 2.10, Secure Boot and Driver Signing](https://uefi.org/specs/UEFI/2.10/32_Secure_Boot_and_Driver_Signing.html) — defines general signature, certificate, public-key, authenticated-variable, and verification concepts. UEFI Secure Boot is not assumed to be identical to ME/CSME authentication.
- [Linux kernel MEI documentation](https://docs.kernel.org/driver-api/mei/mei.html) — documents the host-facing MEI interface and its observable protocol concepts; it does not document Intel’s private firmware signing implementation.

Local project evidence used for scope:

- `firmware-samples/t460-spi-dump.metadata.json` — descriptor, region, FPT, and locally calculated hash metadata only.
- `firmware-samples/t460-ftpr-cpd.metadata.json` — CPD names, boundaries, and layout-derived metadata only.
- `parsers/inspect_ifd.py`, `parsers/inspect_me.py`, and `parsers/inspect_cpd_manifest.py` — read-only inspection tools.

No firmware was downloaded, modified, executed, flashed, or uploaded for this note.
