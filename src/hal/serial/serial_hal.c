/* SPDX-License-Identifier: MIT */
#include "../hal.h"

/*
 * Serial HECI transport HAL (emulation host-driver channel).
 *
 * Maps the HAL's packet recv/send onto COM2 (0x2f8) with a 2-byte little-endian
 * length prefix per packet. An external host-side driver on the other end of
 * that serial line plays the host, so the firmware is driven as a SEPARATE
 * process over a real byte stream (QEMU: a second -serial, TCP-backed).
 *
 * This is still a LOCAL host<->ME transport (COM2 is the wire to the host,
 * exactly like HECI's local link) — it adds no network capability.
 */

#define COM2 0x2f8u
#define SERIAL_MAX 260u

static void out8(uint16_t port, uint8_t v) { __asm__ volatile ("outb %0, %1" : : "a"(v), "Nd"(port)); }
static uint8_t in8(uint16_t port) { uint8_t v; __asm__ volatile ("inb %1, %0" : "=a"(v) : "Nd"(port)); return v; }
static void tx(uint8_t c) { while (!(in8(COM2 + 5) & 0x20)) { } out8(COM2, c); }

static uint8_t frame[SERIAL_MAX];
static unsigned phase, flen, fgot;

static void com2_init(void)
{
    out8(COM2 + 1, 0); out8(COM2 + 3, 0x80);
    out8(COM2, 1); out8(COM2 + 1, 0);
    out8(COM2 + 3, 3); out8(COM2 + 2, 0xc7); out8(COM2 + 4, 0x0b);
}

static enum om_hal_status serial_bringup(void)
{
    com2_init();
    phase = flen = fgot = 0;
    return OM_HAL_OK;
}

static enum om_hal_status serial_send(const uint8_t *b, size_t n)
{
    size_t i;
    if (!b || n > SERIAL_MAX) return OM_HAL_ERROR;
    tx((uint8_t)n);
    tx((uint8_t)(n >> 8));
    for (i = 0; i < n; ++i) tx(b[i]);
    return OM_HAL_OK;
}

/* Non-blocking: drains available COM2 bytes into a frame; returns one complete
 * length-prefixed packet, or OM_HAL_EMPTY when no full frame is ready yet. */
static enum om_hal_status serial_recv(uint8_t *b, size_t cap, size_t *out_len)
{
    if (!b || !out_len) return OM_HAL_ERROR;
    while (in8(COM2 + 5) & 1) {
        uint8_t c = in8(COM2);
        if (phase == 0) { flen = c; phase = 1; }
        else if (phase == 1) {
            flen |= (unsigned)c << 8;
            fgot = 0;
            if (flen == 0 || flen > SERIAL_MAX) { phase = 0; continue; }
            phase = 2;
        } else {
            frame[fgot++] = c;
            if (fgot >= flen) {
                unsigned i;
                phase = 0;
                if (flen > cap) return OM_HAL_ERROR;
                for (i = 0; i < flen; ++i) b[i] = frame[i];
                *out_len = flen;
                return OM_HAL_OK;
            }
        }
    }
    return OM_HAL_EMPTY;
}

static uint32_t serial_ticks(void)
{
    static uint32_t t;
    return ++t;
}

const struct om_hal om_hal_serial = {
    "serial", "emulation-com2", serial_bringup, serial_recv, serial_send, serial_ticks
};
