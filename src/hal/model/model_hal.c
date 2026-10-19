/* SPDX-License-Identifier: MIT */
#include "../hal.h"

/*
 * Emulation HAL.
 *
 * Models the transport as two directional packet queues:
 *   - host -> ME : the firmware reads these via recv()
 *   - ME -> host : the firmware writes these via send()
 * A test (or, later, a real host-side driver) plays the host using
 * om_model_host_send()/om_model_host_recv(). This is NOT loopback: firmware
 * output does not come back as firmware input. No result produced through this
 * HAL is real ME execution.
 */

#define SLOTS 8u
#define SLOT_BYTES 260u /* 4-byte HECI header + up to 256-byte payload */

struct ring {
    uint8_t data[SLOTS][SLOT_BYTES];
    size_t len[SLOTS];
    unsigned head, count;
};

static struct ring h2m; /* host -> ME */
static struct ring m2h; /* ME -> host */

static enum om_hal_status ring_push(struct ring *r, const uint8_t *b, size_t n)
{
    unsigned slot;
    size_t i;
    if (!b || n > SLOT_BYTES) return OM_HAL_ERROR;
    if (r->count == SLOTS) return OM_HAL_AGAIN;
    slot = (r->head + r->count) % SLOTS;
    for (i = 0; i < n; ++i) r->data[slot][i] = b[i];
    r->len[slot] = n;
    ++r->count;
    return OM_HAL_OK;
}

static enum om_hal_status ring_pop(struct ring *r, uint8_t *b, size_t cap, size_t *out_len)
{
    size_t n, i;
    if (!b || !out_len) return OM_HAL_ERROR;
    if (!r->count) return OM_HAL_EMPTY;
    n = r->len[r->head];
    if (n > cap) return OM_HAL_ERROR;
    for (i = 0; i < n; ++i) b[i] = r->data[r->head][i];
    *out_len = n;
    r->head = (r->head + 1) % SLOTS;
    --r->count;
    return OM_HAL_OK;
}

static enum om_hal_status model_bringup(void)
{
    h2m.head = h2m.count = 0;
    m2h.head = m2h.count = 0;
    return OM_HAL_OK;
}

static enum om_hal_status model_recv(uint8_t *buf, size_t cap, size_t *out_len)
{
    return ring_pop(&h2m, buf, cap, out_len); /* firmware consumes host->ME */
}

static enum om_hal_status model_send(const uint8_t *buf, size_t len)
{
    return ring_push(&m2h, buf, len); /* firmware produces ME->host */
}

static uint32_t model_ticks(void)
{
    static uint32_t t; /* deterministic monotonic counter for emulation */
    return ++t;
}

/* Host-side test hooks (the other end of the ring). */
void om_model_reset(void)
{
    model_bringup();
}
enum om_hal_status om_model_host_send(const uint8_t *buf, size_t len)
{
    return ring_push(&h2m, buf, len);
}
enum om_hal_status om_model_host_recv(uint8_t *buf, size_t cap, size_t *out_len)
{
    return ring_pop(&m2h, buf, cap, out_len);
}

const struct om_hal om_hal_model = {
    "model", "emulation", model_bringup, model_recv, model_send, model_ticks
};
