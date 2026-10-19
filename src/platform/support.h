/* SPDX-License-Identifier: MIT */
#ifndef OPENME_PLATFORM_SUPPORT_H
#define OPENME_PLATFORM_SUPPORT_H

#include <stdint.h>

/*
 * Supported-platform registry.
 *
 * OpenME targets the ARC-core ME (generation 6 and earlier) on both desktop
 * and laptop chipsets — it is a CPU/chipset decision, not a laptop-only one.
 * Anything outside that set must be flagged rather than silently attempted, so
 * an unsupported board is WARNED about (and, in a real flash/bring-up path,
 * refused) instead of risking a brick. CSME 11+ is explicitly unsupported: it
 * is locked, and running owner code there is out of scope for this project.
 */

enum om_chipset {
    OM_CHIPSET_EMULATION = 0, /* the QEMU / software-model development target */
    OM_CHIPSET_GM45,          /* mobile, ME 4/5 (ICH9M-E) */
    OM_CHIPSET_GS45,          /* mobile, ME 4/5 */
    OM_CHIPSET_Q45,           /* desktop, ME 5 (ICH10) */
    OM_CHIPSET_IBEXPEAK_M,    /* mobile QM57/QS57, ME 6 */
    OM_CHIPSET_IBEXPEAK_D,    /* desktop 5-series, ME 6 */
    OM_CHIPSET_UNKNOWN
};

enum om_support {
    OM_SUPPORT_OK = 0,       /* recognized, in-scope, development-ready target */
    OM_SUPPORT_EXPERIMENTAL, /* in-scope generation, port not yet validated */
    OM_SUPPORT_UNSUPPORTED   /* out of scope: warn / refuse */
};

struct om_platform_id {
    enum om_chipset chipset;
    uint8_t me_gen; /* detected ME major generation; 0 = unknown/emulation */
};

/* Look up `id` in the registry. *name and *reason are always set to non-NULL
 * strings describing the platform and the support decision. */
enum om_support om_platform_check(struct om_platform_id id,
                                  const char **name, const char **reason);
const char *om_support_name(enum om_support level);

#endif
