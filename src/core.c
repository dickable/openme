/* SPDX-License-Identifier: MIT */
#include "core.h"

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int matches(const uint8_t *p, size_t n, const char *s)
{
    size_t i = 0;
    while (s[i]) {
        if (i >= n || p[i] != (uint8_t)s[i]) return 0;
        ++i;
    }
    return i == n;
}

static size_t copy_text(uint8_t *out, const char *s)
{
    size_t n = 0;
    while (*s) out[n++] = (uint8_t)*s++;
    return n;
}

void om_init(struct om_core *c)
{
    c->state = OM_READY;
    c->requests = 0;
}

const char *om_state_name(enum om_state state)
{
    switch (state) {
    case OM_READY: return "ready";
    case OM_NEGOTIATING: return "negotiating";
    case OM_IDLE: return "idle";
    case OM_CONNECTED: return "connected";
    case OM_SUSPENDED: return "suspended";
    default: return "invalid";
    }
}

static enum om_status validate(const uint8_t *r, size_t n)
{
    size_t payload;
    if (n < OM_HEADER) return OM_BAD_LENGTH;
    if (r[0] != 0x4d || r[1] != 0x4f) return OM_BAD_MAGIC;
    if (r[2] != 1) return OM_BAD_VERSION;
    if (r[3] || r[5]) return OM_BAD_FLAGS;
    if (r[6] || r[7] || r[14] || r[15] || !le32(r + 8))
        return OM_BAD_LENGTH;
    payload = r[12] | ((size_t)r[13] << 8);
    if (payload > OM_PAYLOAD) return OM_TOO_LARGE;
    if (n != OM_HEADER + payload) return OM_BAD_LENGTH;
    return OM_OK;
}

size_t om_handle(struct om_core *c, const uint8_t *r, size_t n,
                 uint8_t *out, size_t cap)
{
    enum om_status status;
    size_t payload = 0, i;
    uint8_t op;
    if (!c || !r || !out || cap < OM_FRAME || r == out) return 0;
    status = validate(r, n);
    op = n >= 5 ? r[4] : 0;
    if (status == OM_OK) {
        const uint8_t *p = r + OM_HEADER;
        size_t count = n - OM_HEADER;
        /* Check payload constraints before any state transition. */
        if (op != 4 && op != 5 && op != 7 && count) {
            status = OM_MALFORMED;
        } else switch (op) {
        case 1: om_init(c); break;
        case 2:
            if (c->state != OM_READY) status = OM_INVALID_STATE;
            else {
                c->state = OM_NEGOTIATING;
                payload = copy_text(out + OM_HEADER, "OPENME-TRANSPORT-1");
            }
            break;
        case 3:
            if (c->state != OM_NEGOTIATING) status = OM_INVALID_STATE;
            else {
                c->state = OM_IDLE;
                payload = copy_text(out + OM_HEADER, "openme.echo");
            }
            break;
        case 4:
        case 5:
            if (c->state != OM_IDLE) status = OM_INVALID_STATE;
            else if (!matches(p, count, "openme.echo")) status = OM_UNKNOWN_CLIENT;
            else if (op == 5) c->state = OM_CONNECTED;
            else payload = copy_text(out + OM_HEADER, "openme.echo|1|256");
            break;
        case 6:
            if (c->state != OM_CONNECTED) status = OM_INVALID_STATE;
            else payload = copy_text(out + OM_HEADER, "1");
            break;
        case 7:
            if (c->state != OM_CONNECTED) status = OM_INVALID_STATE;
            else {
                payload = count;
                for (i = 0; i < count; ++i) out[OM_HEADER + i] = p[i];
            }
            break;
        case 8:
            if (c->state != OM_CONNECTED) status = OM_INVALID_STATE;
            else c->state = OM_IDLE;
            break;
        case 9:
            if (c->state != OM_IDLE && c->state != OM_CONNECTED)
                status = OM_INVALID_STATE;
            else c->state = OM_SUSPENDED;
            break;
        case 10:
            if (c->state != OM_SUSPENDED) status = OM_INVALID_STATE;
            else c->state = OM_IDLE;
            break;
        default: status = OM_UNKNOWN_OPCODE; break;
        }
        if (c->requests != UINT32_MAX) ++c->requests;
    }
    for (i = 0; i < OM_HEADER; ++i) out[i] = 0;
    out[0] = 0x4d; out[1] = 0x4f; out[2] = 1;
    out[3] = status == OM_OK ? 1 : 3;
    out[4] = op; out[5] = (uint8_t)status;
    if (n >= 12) for (i = 8; i < 12; ++i) out[i] = r[i];
    if (!le32(out + 8)) out[8] = 1;
    if (status != OM_OK) payload = 0;
    out[12] = (uint8_t)payload; out[13] = (uint8_t)(payload >> 8);
    return OM_HEADER + payload;
}
