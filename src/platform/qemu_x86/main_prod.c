/* SPDX-License-Identifier: MIT */
#include "../../firmware.h"

/*
 * Production entry point — NO SHELL.
 *
 * A shell is a debug-only surface; shipping one in a real ME image would itself
 * be an attack surface. The production build therefore contains none of the dev
 * shell code: it boots, and enters the autonomous service loop. This file is
 * selected by `build_openme.py --production`; the default (dev) build uses
 * main.c with the interactive shell.
 */

#define UART 0x3f8u

static void out8(uint16_t port, uint8_t value)
{
    __asm__ volatile ("outb %0, %1" : : "a"(value), "Nd"(port));
}
static uint8_t in8(uint16_t port)
{
    uint8_t value;
    __asm__ volatile ("inb %1, %0" : "=a"(value) : "Nd"(port));
    return value;
}
static void putch(char c)
{
    while (!(in8(UART + 5) & 0x20)) { }
    out8(UART, (uint8_t)c);
}
static void puts_serial(const char *s)
{
    while (*s) {
        if (*s == '\n') putch('\r');
        putch(*s++);
    }
}

void firmware_main(uint32_t boot_magic)
{
    static struct om_firmware fw;
    struct om_boot_report r;
    struct flash_dev flash;
    struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };

    out8(UART + 1, 0); out8(UART + 3, 0x80);
    out8(UART, 1); out8(UART + 1, 0);
    out8(UART + 3, 3); out8(UART + 2, 0xc7); out8(UART + 4, 0x0b);

    if (boot_magic != 0x2badb002) {
        puts_serial("fault: invalid Multiboot handoff\n");
        out8(0xf4, 0x11);
        for (;;) __asm__ volatile ("cli; hlt");
    }

    puts_serial("OpenME 0.1 production (no shell)\n");
    flashfs_ram_backend(&flash);
    if (!om_firmware_boot(&fw, &om_hal_model, id, &flash, &r)) {
        puts_serial("boot failed; halting\n");
        out8(0xf4, 0x11);
        for (;;) __asm__ volatile ("cli; hlt");
    }
    puts_serial("boot ok; entering service loop\n");
    om_firmware_power(&fw, 1); /* a real platform drives this from S0 detection */
    om_firmware_run(&fw);      /* never returns */
}
