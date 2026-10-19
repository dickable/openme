/* SPDX-License-Identifier: MIT */
#include "heci.h"
#include "../service/service.h"

/* Wire layouts: Linux drivers/misc/mei/{hw.h,hbm.c,client.c}.
 * Independently implemented HBM 1.0 subset; see docs/hbm-c-milestone.md.
 * This UUID identifies OpenME's test echo service, NOT an Intel service:
 * 6f70656e-6d65-4d45-9a71-000000000001 (uuid_le on the wire). */
static const uint8_t echo_uuid[16] = {
    0x6e, 0x65, 0x70, 0x6f, 0x65, 0x6d, 0x45, 0x4d,
    0x9a, 0x71, 0, 0, 0, 0, 0, 1
};

static void clear(void *memory, size_t n)
{
    uint8_t *p = memory;
    while (n--) *p++ = 0;
}
static void copy(uint8_t *to, const uint8_t *from, size_t n)
{
    while (n--) *to++ = *from++;
}
static int zero(const uint8_t *p, size_t n)
{
    while (n--) if (*p++) return 0;
    return 1;
}
static void disconnect(struct om_heci *h)
{
    h->host = h->host_credit = h->me_credit = h->grant_pending = 0;
    h->assembling = h->pending = h->sending = 0;
    h->received = h->sent = 0;
    clear(h->data, sizeof(h->data));
}
void om_heci_reset(struct om_heci *h)
{
    clear(h, sizeof(*h));
}
static void enqueue(struct om_heci *h, const uint8_t *p, size_t n)
{
    struct om_heci_control *c = &h->control[(h->head + h->count) % OM_HECI_CONTROL_DEPTH];
    clear(c, sizeof(*c));
    copy(c->data, p, n);
    c->length = (uint8_t)n;
    ++h->count;
}
static enum om_heci_result control(struct om_heci *h, const uint8_t *p, size_t n)
{
    uint8_t reply[36] = {0};
    uint8_t status;
    size_t length = 4;
    if (!n) return OM_HECI_FORMAT;
    if (p[0] == 8) {
        if (n != 8 || !zero(p + 3, 5)) return OM_HECI_FORMAT;
        if (!h->started || !h->host) return OM_HECI_STATE;
        if (p[1] != OM_HECI_CLIENT || p[2] != h->host) return OM_HECI_ADDRESS;
        /* One outstanding host read, as used by the Linux MEI client path. */
        if (h->me_credit || h->sending) return OM_HECI_CREDIT;
        h->me_credit = 1;
        return OM_HECI_OK;
    }
    if (p[0] != 1 && p[0] != 2 && p[0] != 4 && p[0] != 5 && p[0] != 6 && p[0] != 7)
        return OM_HECI_UNSUPPORTED;
    if (n != 4) return OM_HECI_FORMAT;
    if (h->count == OM_HECI_CONTROL_DEPTH) return OM_HECI_BUSY;
    if (p[0] != 1 && !h->started) return OM_HECI_STATE;
    reply[0] = p[0] | 0x80;
    switch (p[0]) {
    case 1:
        if (p[1]) return OM_HECI_FORMAT;
        if (h->started) return OM_HECI_STATE;
        if (!p[3]) return OM_HECI_UNSUPPORTED;
        reply[1] = p[3] == 1 && p[2] == 0;
        reply[2] = 0; reply[3] = 1;
        /* Linux accepts me_max_version directly when host_version_supported
         * is false; it does not send a second HOST_START for the downgrade. */
        h->started = 1;
        break;
    case 2:
        if (p[1] > 8 || !zero(p + 2, 2)) return OM_HECI_FORMAT;
        disconnect(h);
        h->started = 0;
        break;
    case 4:
        if (!zero(p + 1, 3)) return OM_HECI_FORMAT;
        reply[4 + OM_HECI_CLIENT / 8] = 1u << (OM_HECI_CLIENT % 8);
        length = 36;
        break;
    case 5:
        if (!zero(p + 2, 2)) return OM_HECI_FORMAT;
        reply[1] = p[1];
        length = 28;
        if (p[1] != OM_HECI_CLIENT) reply[2] = 1;
        else {
            copy(reply + 4, echo_uuid, sizeof(echo_uuid));
            reply[20] = 1; /* service protocol version */
            reply[21] = 1; /* maximum connections */
            /* Dynamic address, independent receive buffer, MTU little-endian. */
            reply[24] = OM_HECI_MTU & 255;
            reply[25] = OM_HECI_MTU >> 8;
        }
        break;
    case 6:
        if (p[3]) return OM_HECI_FORMAT;
        status = p[1] != OM_HECI_CLIENT ? 1 : !p[2] ? 4 :
                 h->host == p[2] ? 2 : h->host ? 3 : 0;
        reply[1] = p[1]; reply[2] = p[2]; reply[3] = status;
        if (!status) {
            disconnect(h);
            h->host = p[2];
            h->grant_pending = 1;
        }
        break;
    case 7:
        if (p[3]) return OM_HECI_FORMAT;
        /* No invented disconnect error status: unmatched pairs are a local
         * protocol error and produce no fabricated wire reply. */
        if (p[1] != OM_HECI_CLIENT || !p[2] || p[2] != h->host) return OM_HECI_ADDRESS;
        reply[1] = p[1]; reply[2] = p[2];
        disconnect(h);
        break;
    }
    enqueue(h, reply, length);
    return OM_HECI_OK;
}
enum om_heci_result om_heci_receive(struct om_heci *h, const uint8_t *p, size_t size)
{
    size_t n;
    int complete;
    if (size < 4) return OM_HECI_FORMAT;
    n = (size_t)p[2] | ((size_t)(p[3] & 1) << 8);
    if (size != n + 4) return OM_HECI_FORMAT;
    /* HBM 1.0 has no negotiated extended, DMA, or internal-header features. */
    if (p[3] & 0x7e) return OM_HECI_UNSUPPORTED;
    if (n > OM_HECI_MTU) return OM_HECI_SIZE;
    complete = !!(p[3] & 0x80);
    if (!p[0] && !p[1]) {
        if (!complete) return OM_HECI_UNSUPPORTED;
        return control(h, p + 4, n);
    }
    if (!h->started || !h->host) return OM_HECI_STATE;
    if (p[0] != OM_HECI_CLIENT || p[1] != h->host) return OM_HECI_ADDRESS;
    if (h->pending || (!h->assembling && !h->host_credit)) return OM_HECI_CREDIT;
    if (n > OM_HECI_MTU - h->received) return OM_HECI_SIZE;
    if (!n && !complete) return OM_HECI_FORMAT;
    if (!h->assembling) h->host_credit = 0;
    copy(h->data + h->received, p + 4, n);
    h->received += n;
    h->assembling = !complete;
    h->pending = complete;
    /* A completed message is handed to the registered service, which produces
     * the reply in place. NULL service == pass the bytes straight back. */
    if (complete && h->service)
        h->received = h->service->handle(h->data, h->received, h->data, OM_HECI_MTU);
    return OM_HECI_OK;
}
static size_t packet(uint8_t *out, uint8_t me, uint8_t host, int complete,
                     const uint8_t *data, size_t n)
{
    out[0] = me; out[1] = host; out[2] = (uint8_t)n;
    out[3] = (uint8_t)((n >> 8) | (complete ? 0x80 : 0));
    copy(out + 4, data, n);
    return 4 + n;
}
size_t om_heci_transmit(struct om_heci *h, uint8_t *out, size_t capacity)
{
    size_t n, result;
    if (h->count) {
        struct om_heci_control *c = &h->control[h->head];
        if (capacity < (size_t)c->length + 4) return 0;
        result = packet(out, 0, 0, 1, c->data, c->length);
        clear(c, sizeof(*c));
        h->head = (h->head + 1) % OM_HECI_CONTROL_DEPTH;
        --h->count;
        return result;
    }
    if (h->grant_pending) {
        uint8_t grant[8] = {8, OM_HECI_CLIENT, 0, 0, 0, 0, 0, 0};
        if (capacity < 12) return 0;
        grant[2] = h->host;
        h->grant_pending = 0;
        h->host_credit = 1;
        return packet(out, 0, 0, 1, grant, sizeof(grant));
    }
    if (!h->pending || (!h->sending && !h->me_credit)) return 0;
    n = h->received - h->sent;
    if (n > OM_HECI_FRAGMENT) n = OM_HECI_FRAGMENT;
    if (capacity < n + 4) return 0;
    h->me_credit = 0;
    h->sending = 1;
    result = packet(out, OM_HECI_CLIENT, h->host, h->sent + n == h->received,
                    h->data + h->sent, n);
    h->sent += n;
    if (h->sent == h->received) {
        h->received = h->sent = 0;
        h->pending = h->sending = 0;
        h->grant_pending = 1;
        clear(h->data, sizeof(h->data));
    }
    return result;
}
const char *om_heci_result_name(enum om_heci_result result)
{
    static const char *const names[] = {
        "ok", "malformed", "unsupported", "invalid-state", "wrong-address",
        "no-credit", "too-large", "queue-full"
    };
    return (unsigned)result < sizeof(names) / sizeof(names[0]) ? names[result] : "unknown";
}
