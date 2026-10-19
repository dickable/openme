/* SPDX-License-Identifier: MIT */
#include "../../src/mei/heci.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct om_heci h;
static unsigned checks;

static size_t unhex(uint8_t *out, const char *hex)
{
    size_t n = 0;
    unsigned value;
    while (*hex) {
        assert(sscanf(hex, "%2x", &value) == 1);
        out[n++] = (uint8_t)value;
        hex += 2;
    }
    return n;
}
static void input(const char *hex, enum om_heci_result want)
{
    uint8_t raw[OM_HECI_PACKET];
    size_t n = unhex(raw, hex);
    struct om_heci before = h;
    assert(om_heci_receive(&h, raw, n) == want);
    if (want != OM_HECI_OK) assert(!memcmp(&before, &h, sizeof(h)));
    ++checks;
}
static void output(const char *hex)
{
    uint8_t want[OM_HECI_PACKET], got[OM_HECI_PACKET];
    size_t n = unhex(want, hex);
    assert(om_heci_transmit(&h, got, sizeof(got)) == n);
    assert(!memcmp(want, got, n));
    ++checks;
}
static void empty(void)
{
    uint8_t got[OM_HECI_PACKET];
    struct om_heci before = h;
    assert(om_heci_transmit(&h, got, sizeof(got)) == 0);
    assert(!memcmp(&before, &h, sizeof(h)));
    ++checks;
}
static void small_output(size_t capacity)
{
    uint8_t got[OM_HECI_PACKET];
    struct om_heci before = h;
    memset(got, 0xa5, sizeof(got));
    assert(om_heci_transmit(&h, got, capacity) == 0);
    assert(!memcmp(&before, &h, sizeof(h)));
    for (size_t i = 0; i < sizeof(got); ++i) assert(got[i] == 0xa5);
    ++checks;
}
static void start(void)
{
    om_heci_reset(&h);
    input("0000048001000001", OM_HECI_OK);
    output("0000048081010001");
}
static void connect_client(void)
{
    start();
    input("0000048006070300", OM_HECI_OK);
    output("0000048086070300");
    small_output(11);
    output("000008800807030000000000");
    empty();
}
static void enumeration(void)
{
    om_heci_reset(&h);
    input("0000048004000000", OM_HECI_STATE);
    input("0000048001000000", OM_HECI_UNSUPPORTED);
    input("0000048001000202", OM_HECI_OK); /* host 2.2 -> device 1.0 */
    small_output(7);
    output("0000048081000001");
    input("0000048001000001", OM_HECI_STATE);
    input("0000048004000000", OM_HECI_OK);
    output("00002480840000008000000000000000000000000000000000000000000000000000000000000000");
    input("0000048005070000", OM_HECI_OK);
    output("00001c80850700006e65706f656d454d9a710000000000010101000000010000");
    input("0000048005090000", OM_HECI_OK);
    output("00001c8085090100000000000000000000000000000000000000000000000000");
    input("0000048006090300", OM_HECI_OK);
    output("0000048086090301");
    input("0000048006070000", OM_HECI_OK);
    output("0000048086070004");
    input("0000048006070300", OM_HECI_OK);
    output("0000048086070300");
    input("0703018000", OM_HECI_CREDIT); /* grant not yet delivered */
    output("000008800807030000000000");
    input("0000048006070300", OM_HECI_OK);
    output("0000048086070302");
    input("0000048006070400", OM_HECI_OK);
    output("0000048086070403");
    empty();
}
static void fragmentation(void)
{
    uint8_t raw[OM_HECI_PACKET], got[OM_HECI_PACKET];
    connect_client();
    input("07040380616263", OM_HECI_ADDRESS);
    input("07030300616263", OM_HECI_OK); /* abc, incomplete */
    empty();
    input("07030000", OM_HECI_FORMAT);
    input("07030380646566", OM_HECI_OK); /* def, complete */
    empty(); /* no host receive credit: must not emit echo */
    input("0703018078", OM_HECI_CREDIT);
    input("000008800807040000000000", OM_HECI_ADDRESS);
    input("000008800807030000000000", OM_HECI_OK);
    input("000008800807030000000000", OM_HECI_CREDIT);
    small_output(9);
    output("07030680616263646566");
    output("000008800807030000000000");
    empty();
    /* Every byte 00..ff in three unequal incoming fragments. Output has
     * four 64-byte fragments and consumes only ONE message credit. */
    input("000008800807030000000000", OM_HECI_OK);
    raw[0] = 7; raw[1] = 3;
    for (size_t at = 0; at < 256;) {
        size_t n = at == 0 ? 99 : at == 99 ? 100 : 57;
        raw[2] = (uint8_t)n; raw[3] = at + n == 256 ? 0x80 : 0;
        for (size_t i = 0; i < n; ++i) raw[i + 4] = (uint8_t)(at + i);
        assert(om_heci_receive(&h, raw, n + 4) == OM_HECI_OK);
        at += n;
    }
    for (size_t at = 0; at < 256; at += 64) {
        small_output(67);
        assert(om_heci_transmit(&h, got, sizeof(got)) == 68);
        assert(got[0] == 7 && got[1] == 3 && got[2] == 64);
        assert(got[3] == (at == 192 ? 0x80 : 0));
        for (size_t i = 0; i < 64; ++i) assert(got[4 + i] == at + i);
    }
    output("000008800807030000000000");
    empty();
    /* Zero length is a complete message, not a zero-length fragment loop. */
    input("07030080", OM_HECI_OK);
    empty();
    input("000008800807030000000000", OM_HECI_OK);
    small_output(3);
    output("07030080");
    output("000008800807030000000000");
    /* Full-size partial message cannot grow past advertised MTU. */
    raw[2] = 0; raw[3] = 1;
    memset(raw + 4, 0x5a, 256);
    assert(om_heci_receive(&h, raw, sizeof(raw)) == OM_HECI_OK);
    input("070301805a", OM_HECI_SIZE);
    assert(h.received == 256 && h.assembling);
    input("07030080", OM_HECI_OK);
    empty();
}
static void lifecycle(void)
{
    connect_client();
    input("0703010001", OM_HECI_OK);
    input("0000048007070400", OM_HECI_ADDRESS);
    input("0000048007070300", OM_HECI_OK);
    output("0000048087070300");
    assert(!h.host && !h.received && !h.me_credit && !h.host_credit);
    empty();
    input("0703018002", OM_HECI_STATE);
    input("0000048006070300", OM_HECI_OK);
    output("0000048086070300");
    output("000008800807030000000000");
    input("0703018003", OM_HECI_OK);
    input("0000048002000000", OM_HECI_OK);
    output("0000048082000000");
    empty();
    input("0000048004000000", OM_HECI_STATE);
    input("0000048001000001", OM_HECI_OK);
    om_heci_reset(&h); /* queued control reply also discarded */
    empty();
    connect_client();
    input("000008800807030000000000", OM_HECI_OK);
    input("0703018004", OM_HECI_OK);
    om_heci_reset(&h); /* pending echo and all credits discarded */
    empty();
    assert(!h.started && !h.host && !h.received && !h.me_credit);
    for (size_t i = 0; i < sizeof(h.data); ++i) assert(h.data[i] == 0);
}
static void backpressure(void)
{
    start();
    for (unsigned round = 0; round < 10; ++round) {
        for (unsigned i = 0; i < OM_HECI_CONTROL_DEPTH; ++i)
            input("0000048005070000", OM_HECI_OK);
        input("0000048006070300", OM_HECI_BUSY);
        small_output(31);
        for (unsigned i = 0; i < OM_HECI_CONTROL_DEPTH; ++i)
            output("00001c80850700006e65706f656d454d9a710000000000010101000000010000");
        empty();
    }
    assert(!h.host);
}
static void malformed(void)
{
    struct guarded { uint8_t pre[16]; struct om_heci state; uint8_t post[16]; } g;
    uint8_t raw[OM_HECI_PACKET + 8], out[OM_HECI_PACKET + 2];
    uint32_t random = 0x1968;
    connect_client();
    input("", OM_HECI_FORMAT);
    input("00000480040000", OM_HECI_FORMAT);
    input("000004800400000000", OM_HECI_FORMAT); /* padding not accepted by packet API */
    input("0000049004000000", OM_HECI_UNSUPPORTED);
    input("0000048204000000", OM_HECI_UNSUPPORTED);
    input("0000040004000000", OM_HECI_UNSUPPORTED);
    input("0000048013000000", OM_HECI_UNSUPPORTED);
    input("0000048004010000", OM_HECI_FORMAT);
    input("0000048005070100", OM_HECI_FORMAT);
    input("000008800807030100000000", OM_HECI_FORMAT);
    input("0000048006070301", OM_HECI_FORMAT);
    input("0000048002090000", OM_HECI_FORMAT);
    input("0003048004000000", OM_HECI_ADDRESS);
    memset(&g, 0xa5, sizeof(g));
    om_heci_reset(&g.state);
    for (unsigned i = 0; i < 10000; ++i) {
        size_t n = i % sizeof(raw);
        struct om_heci before = g.state;
        for (size_t j = 0; j < n; ++j) {
            random = random * 1664525u + 1013904223u;
            raw[j] = (uint8_t)(random >> 24);
        }
        if (om_heci_receive(&g.state, raw, n) != OM_HECI_OK)
            assert(!memcmp(&before, &g.state, sizeof(before)));
        memset(out, 0xa5, sizeof(out));
        assert(om_heci_transmit(&g.state, out + 1, OM_HECI_PACKET) <= OM_HECI_PACKET);
        assert(out[0] == 0xa5 && out[sizeof(out) - 1] == 0xa5);
        for (size_t j = 0; j < 16; ++j) assert(g.pre[j] == 0xa5 && g.post[j] == 0xa5);
    }
}
int main(void)
{
    enumeration(); fragmentation(); lifecycle(); backpressure(); malformed();
    printf("HECI: %u checks and 10000 malformed cases passed\n", checks);
    return 0;
}
