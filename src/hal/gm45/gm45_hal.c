/* SPDX-License-Identifier: MIT */
#include "../hal.h"
#include "gm45_regs.h"

/*
 * GM45 (ThinkPad X200/T400 class, ME 4/5 on ICH9M-E) HAL — reference port.
 *
 * STATUS: stub. This file is the home of the first real-hardware port and
 * defines the interface the rest of OpenME will satisfy, but none of the
 * hardware operations are implemented yet. Every call returns
 * OM_HAL_NOT_IMPLEMENTED on purpose, so the build links and the architecture
 * is exercised while the reverse-engineering work proceeds.
 *
 * What each operation must eventually do (see docs/me6-target.md roadmap):
 *
 *   bringup():
 *     - locate the MEI device and map its BAR0 (see gm45_regs.h for the
 *       documented register layout and the per-chipset device location);
 *     - perform the host/ME reset handshake using H_CSR.RST / H_CSR.RDY and
 *       ME_CSR_HA.RST / ME_CSR_HA.RDY, then wait for ME ready;
 *     - the ME-SIDE (ARC) firmware bring-up this port ultimately replaces is
 *       undocumented and is the core reverse-engineering effort — it is NOT a
 *       matter of writing these register pokes.
 *
 *   recv(): read ME_CSR_HA read/write pointers to find pending words, drain
 *     them from ME_CB_RW into `buf` as one HECI packet, advance the read
 *     pointer, and acknowledge via H_CSR.IG. OM_HAL_EMPTY when CBRP == CBWP.
 *
 *   send(): check free space from H_CSR pointers/depth, write the packet words
 *     to H_CB_WW, then ring the ME doorbell via H_CSR.IG.
 *
 * This port does not bypass any verification. GM45-class parts permit owner
 * firmware (the ME is even removable there under coreboot); if a specific
 * target turns out to enforce verification that would have to be defeated, it
 * is out of scope rather than a problem to be worked around.
 */

static enum om_hal_status gm45_bringup(void)
{
    return OM_HAL_NOT_IMPLEMENTED;
}

static enum om_hal_status gm45_recv(uint8_t *buf, size_t cap, size_t *out_len)
{
    (void)buf;
    (void)cap;
    (void)out_len;
    return OM_HAL_NOT_IMPLEMENTED;
}

static enum om_hal_status gm45_send(const uint8_t *buf, size_t len)
{
    (void)buf;
    (void)len;
    return OM_HAL_NOT_IMPLEMENTED;
}

static uint32_t gm45_ticks(void)
{
    /* TODO: a real GM45 timer source (e.g. an ME timer or the chipset HPET/ACPI
     * timer). The stub returns 0 so timeouts never advance until implemented. */
    return 0;
}

const struct om_hal om_hal_gm45 = {
    "gm45", "ME 4/5 (GM45/ICH9M-E)", gm45_bringup, gm45_recv, gm45_send, gm45_ticks
};
