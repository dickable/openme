/* SPDX-License-Identifier: MIT */
#include "hal.h"

const char *om_hal_status_name(enum om_hal_status status)
{
    static const char *const names[] = {
        "ok", "not-implemented", "empty", "again", "error"
    };
    return (unsigned)status < sizeof(names) / sizeof(names[0])
           ? names[status] : "unknown";
}
