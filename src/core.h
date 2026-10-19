/* SPDX-License-Identifier: MIT */
#ifndef OPENME_CORE_H
#define OPENME_CORE_H

#include <stddef.h>
#include <stdint.h>

/* OpenME's existing framed-v1 laboratory protocol, not the Intel MEI ABI. */
#define OM_HEADER 16u
#define OM_PAYLOAD 256u
#define OM_FRAME (OM_HEADER + OM_PAYLOAD)

enum om_state { OM_READY, OM_NEGOTIATING, OM_IDLE, OM_CONNECTED, OM_SUSPENDED };
enum om_status {
    OM_OK, OM_BAD_MAGIC, OM_BAD_VERSION, OM_BAD_FLAGS, OM_BAD_LENGTH,
    OM_UNKNOWN_OPCODE, OM_NOT_READY, OM_INVALID_STATE, OM_UNKNOWN_CLIENT,
    OM_TOO_LARGE, OM_QUEUE_FULL, OM_MALFORMED, OM_UNSUPPORTED
};
struct om_core {
    enum om_state state;
    uint32_t requests;
};

void om_init(struct om_core *core);
const char *om_state_name(enum om_state state);
/* Distinct input/output buffers. Zero return means no output/state change.
 * Output capacity must be OM_FRAME, even for errors. No allocation or libc. */
size_t om_handle(struct om_core *core, const uint8_t *request, size_t length,
                 uint8_t *response, size_t capacity);

#endif
