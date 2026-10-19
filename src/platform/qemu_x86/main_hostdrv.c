/* SPDX-License-Identifier: MIT */
#include "../../firmware.h"

/*
 * Host-driver entry point — NO SHELL.
 *
 * Boots with the serial (COM2) HECI HAL and runs the autonomous service loop,
 * so an external host-side driver drives the firmware over COM2 as a separate
 * process. COM1 carries a one-line readiness banner for the driver to sync on.
 * Selected by `build_openme.py --hostdriver`.
 */

#define COM1 0x3f8u

static void out8(uint16_t port, uint8_t v) { __asm__ volatile ("outb %0, %1" : : "a"(v), "Nd"(port)); }
static uint8_t in8(uint16_t port) { uint8_t v; __asm__ volatile ("inb %1, %0" : "=a"(v) : "Nd"(port)); return v; }
static void putch(char c) { while (!(in8(COM1 + 5) & 0x20)) { } out8(COM1, (uint8_t)c); }
static void puts_serial(const char *s) { while (*s) { if (*s == '\n') putch('\r'); putch(*s++); } }

void firmware_main(uint32_t boot_magic)
{
    static struct om_firmware fw;
    struct om_boot_report r;
    struct flash_dev flash;
    struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };

    out8(COM1 + 1, 0); out8(COM1 + 3, 0x80);
    out8(COM1, 1); out8(COM1 + 1, 0);
    out8(COM1 + 3, 3); out8(COM1 + 2, 0xc7); out8(COM1 + 4, 0x0b);

    if (boot_magic != 0x2badb002) {
        puts_serial("fault: invalid Multiboot handoff\n");
        out8(0xf4, 0x11);
        for (;;) __asm__ volatile ("cli; hlt");
    }

    puts_serial("OpenME hostdriver: booting\n");
    flashfs_ram_backend(&flash);
    if (!om_firmware_boot(&fw, &om_hal_serial, id, &flash, &r)) { /* bringup inits COM2 */
        puts_serial("boot failed; halting\n");
        out8(0xf4, 0x11);
        for (;;) __asm__ volatile ("cli; hlt");
    }
    om_firmware_power(&fw, 1);
    puts_serial("hostdriver ready\n"); /* sync marker for the external driver */
    om_firmware_run(&fw);              /* services COM2 forever */
}
