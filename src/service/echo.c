/* SPDX-License-Identifier: MIT */
#include "service.h"

/* Identity: the reply is the request. Tolerates in == out, so the common
 * in-place call does no copying at all. */
static size_t echo_handle(const uint8_t *in, size_t in_len, uint8_t *out, size_t cap)
{
    size_t i;
    if (in_len > cap) in_len = cap;
    if (in != out)
        for (i = 0; i < in_len; ++i) out[i] = in[i];
    return in_len;
}

const struct om_service om_service_echo = {
    "openme.echo",
    { 0x6e, 0x65, 0x70, 0x6f, 0x65, 0x6d, 0x45, 0x4d,
      0x9a, 0x71, 0, 0, 0, 0, 0, 1 },
    echo_handle
};
