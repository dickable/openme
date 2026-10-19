/* SPDX-License-Identifier: MIT */
#include "support.h"
#include <stddef.h>

struct entry {
    enum om_chipset chipset;
    const char *name;
    uint8_t me_gen_expected;
    enum om_support level;
    const char *reason;
};

/* The known platforms. Desktop and mobile both appear on purpose — the target
 * is the ARC-ME generations, regardless of form factor. Real ports move from
 * EXPERIMENTAL to OK only once validated on that exact chipset. */
static const struct entry registry[] = {
    { OM_CHIPSET_EMULATION,   "emulation",                    0, OM_SUPPORT_OK,
      "software/QEMU model target" },
    { OM_CHIPSET_GM45,        "GM45 (mobile)",                4, OM_SUPPORT_EXPERIMENTAL,
      "ARC ME 4/5; HAL not yet validated" },
    { OM_CHIPSET_GS45,        "GS45 (mobile)",                4, OM_SUPPORT_EXPERIMENTAL,
      "ARC ME 4/5; HAL not yet validated" },
    { OM_CHIPSET_Q45,         "Q45 (desktop)",                5, OM_SUPPORT_EXPERIMENTAL,
      "ARC ME 5; HAL not yet validated" },
    { OM_CHIPSET_IBEXPEAK_M,  "Ibex Peak-M QM57 (mobile)",    6, OM_SUPPORT_EXPERIMENTAL,
      "ARC ME 6; HAL not yet validated" },
    { OM_CHIPSET_IBEXPEAK_D,  "Ibex Peak 5-series (desktop)", 6, OM_SUPPORT_EXPERIMENTAL,
      "ARC ME 6; HAL not yet validated" },
};

enum om_support om_platform_check(struct om_platform_id id,
                                  const char **name, const char **reason)
{
    size_t i;
    for (i = 0; i < sizeof(registry) / sizeof(registry[0]); ++i) {
        if (registry[i].chipset != id.chipset)
            continue;
        *name = registry[i].name;
        /* A recognized chipset is still out of scope if the detected ME
         * generation is above the ARC ceiling (CSME 11+ is locked). */
        if (id.chipset != OM_CHIPSET_EMULATION && id.me_gen > 6) {
            *reason = "ME generation above 6 (CSME 11+ is locked); out of scope";
            return OM_SUPPORT_UNSUPPORTED;
        }
        *reason = registry[i].reason;
        return registry[i].level;
    }
    *name = "unknown";
    *reason = "chipset not in the supported registry";
    return OM_SUPPORT_UNSUPPORTED;
}

const char *om_support_name(enum om_support level)
{
    static const char *const names[] = { "ok", "experimental", "unsupported" };
    return (unsigned)level < sizeof(names) / sizeof(names[0]) ? names[level] : "unknown";
}
