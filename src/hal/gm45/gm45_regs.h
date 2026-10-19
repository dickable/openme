/* SPDX-License-Identifier: MIT */
#ifndef OPENME_HAL_GM45_REGS_H
#define OPENME_HAL_GM45_REGS_H

/*
 * GM45 / ICH9M-E HECI (MEI) register reference.
 *
 * These are the documented host-side HECI registers (see the Linux kernel
 * drivers/misc/mei/hw-me-regs.h and the public HECI interface description).
 * They are the stable, documented part of the ME — the footing this port is
 * built on. The undocumented part is the ME-side (ARC) firmware behaviour,
 * which is reverse-engineering work, not captured here.
 *
 * The MEI device location is chipset-specific. On ICH9-class platforms the
 * controller is typically at PCI 00:03.0; on 5-series+ PCH it moves to
 * 00:16.0. Confirm the exact bus/device/function and BAR0 against the target
 * board (e.g. with lspci) rather than hardcoding a guess.
 *
 * The four registers below are memory-mapped at BAR0 of the MEI device.
 */

#define GM45_MEI_H_CB_WW   0x00u /* Host circular buffer write window */
#define GM45_MEI_H_CSR     0x04u /* Host control/status */
#define GM45_MEI_ME_CB_RW  0x08u /* ME circular buffer read window */
#define GM45_MEI_ME_CSR_HA 0x0Cu /* ME control/status (host access) */

/* H_CSR (host control/status) fields. */
#define GM45_H_CSR_IE   0x00000001u /* host interrupt enable */
#define GM45_H_CSR_IS   0x00000002u /* host interrupt status (write 1 to clear) */
#define GM45_H_CSR_IG   0x00000004u /* host interrupt generate (doorbell) */
#define GM45_H_CSR_RDY  0x00000008u /* host ready */
#define GM45_H_CSR_RST  0x00000010u /* host reset */
#define GM45_H_CSR_CBRP 0x0000FF00u /* circular buffer read pointer  (bits 8..15) */
#define GM45_H_CSR_CBWP 0x00FF0000u /* circular buffer write pointer (bits 16..23) */
#define GM45_H_CSR_CBD  0xFF000000u /* circular buffer depth         (bits 24..31) */

/* ME_CSR_HA (ME control/status, host access) fields. */
#define GM45_ME_CSR_IE   0x00000001u /* ME interrupt enable */
#define GM45_ME_CSR_IS   0x00000002u /* ME interrupt status */
#define GM45_ME_CSR_IG   0x00000004u /* ME interrupt generate */
#define GM45_ME_CSR_RDY  0x00000008u /* ME ready */
#define GM45_ME_CSR_RST  0x00000010u /* ME reset */
#define GM45_ME_CSR_CBRP 0x0000FF00u
#define GM45_ME_CSR_CBWP 0x00FF0000u
#define GM45_ME_CSR_CBD  0xFF000000u

/* Circular buffer slots are 32-bit words; payloads are word-granular. */
#define GM45_MEI_SLOT_BYTES 4u

#endif
