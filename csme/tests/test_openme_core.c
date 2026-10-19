/* SPDX-License-Identifier: MIT */
#include "../../src/core.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t request[OM_FRAME + 1], response[OM_FRAME + 2];
static struct om_core core;
static unsigned checks;

static size_t make(uint8_t op, const void *payload, size_t n)
{
    memset(request, 0, sizeof(request));
    request[0] = 0x4d; request[1] = 0x4f; request[2] = 1;
    request[4] = op; request[8] = 0xab; request[11] = 0x12;
    request[12] = (uint8_t)n; request[13] = (uint8_t)(n >> 8);
    if (n) memcpy(request + OM_HEADER, payload, n);
    return OM_HEADER + n;
}

static void check(size_t n, enum om_status status, const void *payload, size_t len)
{
    size_t got;
    memset(response, 0xa5, sizeof(response));
    got = om_handle(&core, request, n, response + 1, OM_FRAME);
    assert(got == OM_HEADER + len);
    assert(response[0] == 0xa5 && response[OM_FRAME + 1] == 0xa5);
    assert(response[6] == status);
    assert(response[4] == (status == OM_OK ? 1 : 3));
    assert(response[13] == (len & 255) && response[14] == (len >> 8));
    if (len) assert(memcmp(response + 1 + OM_HEADER, payload, len) == 0);
    ++checks;
}

int main(void)
{
    uint8_t data[OM_PAYLOAD];
    uint32_t random = 0x10203040;
    size_t n;
    om_init(&core);
    assert(core.state == OM_READY);
    check(make(7, NULL, 0), OM_INVALID_STATE, NULL, 0);
    check(make(2, NULL, 0), OM_OK, "OPENME-TRANSPORT-1", 18);
    check(make(2, NULL, 0), OM_INVALID_STATE, NULL, 0);
    check(make(3, NULL, 0), OM_OK, "openme.echo", 11);
    check(make(4, "openme.echo", 11), OM_OK, "openme.echo|1|256", 17);
    check(make(5, "missing", 7), OM_UNKNOWN_CLIENT, NULL, 0);
    check(make(5, "openme.echo", 11), OM_OK, NULL, 0);
    check(make(6, NULL, 0), OM_OK, "1", 1);
    for (unsigned i = 0; i < OM_PAYLOAD; ++i) data[i] = (uint8_t)i;
    check(make(7, data, sizeof(data)), OM_OK, data, sizeof(data));
    assert(response[9] == 0xab && response[12] == 0x12);
    check(make(7, NULL, 0), OM_OK, NULL, 0);

    /* A malformed RESET must not erase a live connection. */
    n = make(1, NULL, 0); request[6] = 1;
    check(n, OM_BAD_LENGTH, NULL, 0);
    assert(core.state == OM_CONNECTED);
    n = make(1, NULL, 0); request[0] = 0;
    check(n, OM_BAD_MAGIC, NULL, 0);
    n = make(1, NULL, 0); request[2] = 2;
    check(n, OM_BAD_VERSION, NULL, 0);
    n = make(1, NULL, 0); request[3] = 1;
    check(n, OM_BAD_FLAGS, NULL, 0);
    n = make(1, NULL, 0); request[5] = 1;
    check(n, OM_BAD_FLAGS, NULL, 0);
    n = make(1, NULL, 0); request[8] = request[11] = 0;
    check(n, OM_BAD_LENGTH, NULL, 0);
    n = make(1, NULL, 0); request[12] = 1; request[13] = 1;
    check(n, OM_TOO_LARGE, NULL, 0);
    check(make(1, NULL, 0) + 1, OM_BAD_LENGTH, NULL, 0);
    check(make(1, "x", 1), OM_MALFORMED, NULL, 0);
    assert(core.state == OM_CONNECTED);
    check(make(0xff, NULL, 0), OM_UNKNOWN_OPCODE, NULL, 0);

    for (n = 0; n < OM_HEADER; ++n) {
        make(1, NULL, 0);
        check(n, OM_BAD_LENGTH, NULL, 0);
    }
    n = make(1, NULL, 0);
    assert(om_handle(&core, request, n, response, OM_FRAME - 1) == 0);
    assert(om_handle(NULL, request, n, response, OM_FRAME) == 0);
    assert(om_handle(&core, NULL, n, response, OM_FRAME) == 0);
    assert(om_handle(&core, request, n, NULL, OM_FRAME) == 0);
    assert(om_handle(&core, request, n, request, OM_FRAME) == 0);
    assert(core.state == OM_CONNECTED);
    check(make(9, NULL, 0), OM_OK, NULL, 0);
    check(make(7, data, 1), OM_INVALID_STATE, NULL, 0);
    check(make(10, NULL, 0), OM_OK, NULL, 0);
    assert(core.state == OM_IDLE);
    check(make(7, data, 1), OM_INVALID_STATE, NULL, 0);
    check(make(5, "openme.echo", 11), OM_OK, NULL, 0);
    check(make(8, NULL, 0), OM_OK, NULL, 0);
    check(make(1, NULL, 0), OM_OK, NULL, 0);
    assert(core.state == OM_READY && core.requests == 1);
    core.requests = UINT32_MAX;
    check(make(0xff, NULL, 0), OM_UNKNOWN_OPCODE, NULL, 0);
    assert(core.requests == UINT32_MAX);

    /* Deterministic malformed-input sweep, with exact capacity canaries. */
    for (unsigned sample = 0; sample < 10000; ++sample) {
        for (size_t i = 0; i < sizeof(request); ++i) {
            random = random * 1664525u + 1013904223u;
            request[i] = (uint8_t)(random >> 24);
        }
        n = sample % sizeof(request);
        memset(response, 0xa5, sizeof(response));
        size_t got = om_handle(&core, request, n, response + 1, OM_FRAME);
        assert(got >= OM_HEADER && got <= OM_FRAME);
        assert(response[0] == 0xa5 && response[OM_FRAME + 1] == 0xa5);
        assert(core.state == OM_READY);
    }
    printf("OpenME core: %u response checks + 10000 malformed cases passed\n", checks);
    return 0;
}
