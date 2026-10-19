/* SPDX-License-Identifier: MIT */
#include "../../firmware.h"

/* Shell-free test entry. COM2 carries a versioned, CRC32-checked NOR snapshot,
 * NOT HECI and NOT a physical flash controller. The host watchdog bounds waits.
 * No packet services are powered on. See docs/cold-persistence.md for framing. */
#define COM1 0x3f8u
#define COM2 0x2f8u
#define SNAPSHOT_CAPACITY 4096u
#define CHUNK 16u
#define ACK 6u
static uint8_t snapshot[SNAPSHOT_CAPACITY];

static void out8(uint16_t port, uint8_t v) { __asm__ volatile ("outb %0, %1" : : "a"(v), "Nd"(port)); }
static uint8_t in8(uint16_t port) { uint8_t v; __asm__ volatile ("inb %1, %0" : "=a"(v) : "Nd"(port)); return v; }
static void uart_init(uint16_t port)
{
    out8(port + 1, 0); out8(port + 3, 0x80);
    out8(port, 1); out8(port + 1, 0);
    out8(port + 3, 3); out8(port + 2, 0xc7); out8(port + 4, 0x0b);
}
static void tx(uint16_t port, uint8_t c)
{
    while (!(in8(port + 5) & 0x20)) { }
    out8(port, c);
}
static uint8_t rx(void)
{
    uint8_t status;
    do { status = in8(COM2 + 5); } while (!(status & 1));
    if (status & 0x1e) { /* overrun, parity, framing, or break */
        out8(0xf4, 0x11);
        for (;;) __asm__ volatile ("cli; hlt");
    }
    return in8(COM2);
}
static void text(const char *s)
{
    while (*s) {
        if (*s == '\n') tx(COM1, '\r');
        tx(COM1, (uint8_t)*s++);
    }
}
static void decimal(uint32_t n)
{
    char digits[10];
    unsigned used = 0;
    do { digits[used++] = (char)('0' + n % 10); n /= 10; } while (n);
    while (used) tx(COM1, (uint8_t)digits[--used]);
}
static void finish(uint8_t code)
{
    while (!(in8(COM1 + 5) & 0x40) || !(in8(COM2 + 5) & 0x40)) { }
    out8(0xf4, code);
    for (;;) __asm__ volatile ("cli; hlt");
}
static void fail(const char *reason)
{
    text("persist fault: "); text(reason); text("\n");
    finish(0x11);
}
static uint32_t read32(void)
{
    uint32_t n = 0;
    for (unsigned i = 0; i < 4; ++i) n |= (uint32_t)rx() << (8 * i);
    return n;
}
static void write32(uint32_t n)
{
    for (unsigned i = 0; i < 4; ++i) tx(COM2, (uint8_t)(n >> (8 * i)));
}
static void magic(const char *s)
{
    for (unsigned i = 0; i < 4; ++i) tx(COM2, (uint8_t)s[i]);
}
static uint32_t crc32(const uint8_t *p, uint32_t n)
{
    uint32_t c = UINT32_MAX;
    while (n--) {
        c ^= *p++;
        for (unsigned bit = 0; bit < 8; ++bit)
            c = (c >> 1) ^ ((c & 1) ? 0xedb88320u : 0);
    }
    return ~c;
}

void firmware_main(uint32_t boot_magic)
{
    static struct om_firmware fw;
    struct om_boot_report report;
    struct flash_dev flash;
    struct flashfs check;
    struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };
    uint32_t total = om_nor_total(), expected_crc, length;
    int erased = 1;
    const char *input_magic = "OMI1";

    uart_init(COM1); uart_init(COM2);
    if (boot_magic != 0x2badb002) fail("invalid Multiboot handoff");
    if (!total || total > sizeof(snapshot)) fail("NOR exceeds snapshot capacity");
    text("OpenME persist ready bytes="); decimal(total); text("\n");
    magic("OMP1"); write32(total);
    for (unsigned i = 0; i < 4; ++i)
        if (rx() != (uint8_t)input_magic[i]) fail("seed protocol");
    length = read32(); expected_crc = read32();
    if (length != total) fail("seed length");
    tx(COM2, ACK);
    for (uint32_t at = 0; at < total;) {
        uint32_t end = at + CHUNK < total ? at + CHUNK : total;
        while (at < end) {
            snapshot[at] = rx();
            if (snapshot[at++] != 0xff) erased = 0;
        }
        tx(COM2, ACK);
    }
    if (crc32(snapshot, total) != expected_crc) fail("seed CRC32");
    om_nor_load(snapshot, total);
    flashfs_ram_backend(&flash);
    /* The generic boot currently formats an unmountable store. Never let this
     * snapshot test silently replace a non-erased, invalid input with blanks. */
    if (!erased && flashfs_mount(&check, &flash) != FLASHFS_OK)
        fail("non-erased seed is not mountable");
    if (!om_firmware_boot(&fw, &om_hal_model, id, &flash, &report))
        fail("firmware boot");
    if (report.network || fw.powered) fail("capability/power invariant");
    if (om_nor_save(snapshot, sizeof(snapshot)) != total) fail("snapshot extent");
    magic("OMO1"); write32(total); write32(crc32(snapshot, total));
    write32(report.boot_count); write32((uint32_t)report.fs_formatted);
    if (rx() != ACK) fail("snapshot header acknowledgement");
    for (uint32_t at = 0; at < total;) {
        uint32_t end = at + CHUNK < total ? at + CHUNK : total;
        while (at < end) tx(COM2, snapshot[at++]);
        if (rx() != ACK) fail("snapshot acknowledgement");
    }
    text("persist: boot-count="); decimal(report.boot_count);
    text(" formatted="); decimal((uint32_t)report.fs_formatted);
    text(" net=none powered=0\n");
    finish(0x10);
}
