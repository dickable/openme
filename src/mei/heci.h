/* SPDX-License-Identifier: MIT */
#ifndef OPENME_HECI_H
#define OPENME_HECI_H

#include <stddef.h>
#include <stdint.h>

#define OM_HECI_MTU 256u
#define OM_HECI_PACKET (4u + OM_HECI_MTU)
#define OM_HECI_FRAGMENT 64u
#define OM_HECI_CONTROL_DEPTH 4u
#define OM_HECI_CLIENT 7u

struct om_service; /* src/service/service.h; set to dispatch delivered messages */

enum om_heci_result {
    OM_HECI_OK, OM_HECI_FORMAT, OM_HECI_UNSUPPORTED, OM_HECI_STATE,
    OM_HECI_ADDRESS, OM_HECI_CREDIT, OM_HECI_SIZE, OM_HECI_BUSY
};
struct om_heci_control {
    uint8_t data[36];
    uint8_t length;
};
struct om_heci {
    struct om_heci_control control[OM_HECI_CONTROL_DEPTH];
    uint8_t data[OM_HECI_MTU];
    size_t received, sent;
    uint8_t head, count, started, host;
    uint8_t host_credit, me_credit, grant_pending;
    uint8_t assembling, pending, sending;
    /* Optional: service applied to a fully-assembled message before reply.
     * NULL means pass the message straight back unchanged (plain echo). */
    const struct om_service *service;
};

/* Packet boundary: four-byte little-endian header + EXACT payload length.
 * The hardware adapter must remove slot padding. No MMIO/PCI semantics here.
 * Calls are serialized. Input/output must not alias this state object.
 * Rejected input and insufficient output capacity leave state unchanged. */
void om_heci_reset(struct om_heci *h);
enum om_heci_result om_heci_receive(struct om_heci *h, const uint8_t *packet, size_t size);
/* Returns one packet, or zero (empty/credit-blocked/insufficient capacity).
 * Pass OM_HECI_PACKET capacity to distinguish empty from insufficient space.
 * A hardware adapter must reserve TX space BEFORE dequeuing. */
size_t om_heci_transmit(struct om_heci *h, uint8_t *packet, size_t capacity);
const char *om_heci_result_name(enum om_heci_result result);

#endif
