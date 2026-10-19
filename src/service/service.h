/* SPDX-License-Identifier: MIT */
#ifndef OPENME_SERVICE_H
#define OPENME_SERVICE_H

#include <stddef.h>
#include <stdint.h>

/*
 * A HECI service: it turns one complete inbound message into a reply.
 *
 * This is the single service contract for OpenME. The HECI layer delivers a
 * fully-assembled message to handle(); whatever it returns is sent back. New
 * capabilities are added as new `struct om_service` implementations rather than
 * by editing the transport — the transport (src/mei/heci.c) has no service
 * logic of its own anymore.
 *
 * `in` and `out` MAY alias (in-place transformation is allowed and is the
 * common case). Return the reply length (clamped to `cap`), or 0 for
 * "consume the message, send no reply".
 */
struct om_service {
    const char *name;
    uint8_t uuid[16];
    size_t (*handle)(const uint8_t *in, size_t in_len, uint8_t *out, size_t cap);
};

/* The project's test/echo service (its UUID matches the one the HECI layer
 * advertises for client enumeration). */
extern const struct om_service om_service_echo;

#endif
