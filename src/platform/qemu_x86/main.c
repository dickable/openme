/* SPDX-License-Identifier: MIT */
#include "../../core.h"
#include "../../mei/heci.h"
#include "../../hal/hal.h"
#include "../../fs/flashfs.h"
#include "../support.h"
#include "../../firmware.h"

/* The QEMU target pairs with the emulation (model) HAL. A real-hardware build
 * would pair its boot entry with a hardware HAL such as om_hal_gm45. */
#define PLATFORM_HAL om_hal_model

#define UART 0x3f8u
static struct om_core core;
static struct om_heci heci;
static uint8_t request[OM_FRAME], response[OM_FRAME];
static char line[2 * OM_FRAME + 16];

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
static int equal(const char *a, const char *b)
{
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}
static int nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static void print_hex(const uint8_t *data, size_t length)
{
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < length; ++i) {
        putch(hex[data[i] >> 4]); putch(hex[data[i] & 15]);
    }
    puts_serial("\n");
}
static void frame(const char *text, int is_heci)
{
    size_t n = 0, result;
    while (*text) {
        int a = nibble(text[0]), b;
        if (!text[1] || a < 0 || (b = nibble(text[1])) < 0 || n == OM_FRAME) {
            puts_serial(is_heci ? "error: invalid heci hex\n" : "error: invalid frame hex\n");
            return;
        }
        request[n++] = (uint8_t)((a << 4) | b);
        text += 2;
    }
    if (is_heci) {
        puts_serial("heci status=");
        puts_serial(om_heci_result_name(om_heci_receive(&heci, request, n)));
        puts_serial("\n");
        return;
    }
    result = om_handle(&core, request, n, response, sizeof(response));
    puts_serial("reply ");
    print_hex(response, result);
}
static int bytes_equal(const uint8_t *a, const uint8_t *b, size_t n)
{
    for (size_t i = 0; i < n; ++i)
        if (a[i] != b[i]) return 0;
    return 1;
}

/* Exercise the flash filesystem in the guest: format, write, read back, update,
 * delete, then remount and confirm the value persisted. Returns 0 on full pass,
 * otherwise the step number that failed. */
static int fs_selftest(void)
{
    struct flashfs fs;
    struct flash_dev dev;
    uint8_t v[FLASHFS_MAX_VALUE];
    uint32_t n = 0;
    const uint8_t a[] = "hello";
    const uint8_t b[] = "HELLO-version-2";
    flashfs_ram_backend(&dev);
    if (flashfs_format(&fs, &dev) != FLASHFS_OK) return 1;
    if (flashfs_set(&fs, 1, a, 5) != FLASHFS_OK) return 2;
    if (flashfs_get(&fs, 1, v, sizeof(v), &n) != FLASHFS_OK || n != 5 || !bytes_equal(v, a, 5)) return 3;
    if (flashfs_set(&fs, 1, b, 15) != FLASHFS_OK) return 4;   /* update supersedes */
    if (flashfs_get(&fs, 1, v, sizeof(v), &n) != FLASHFS_OK || n != 15 || !bytes_equal(v, b, 15)) return 5;
    if (flashfs_set(&fs, 2, a, 5) != FLASHFS_OK) return 6;
    if (flashfs_delete(&fs, 2) != FLASHFS_OK) return 7;
    if (flashfs_get(&fs, 2, v, sizeof(v), &n) != FLASHFS_NOT_FOUND) return 8;
    if (flashfs_mount(&fs, &dev) != FLASHFS_OK) return 9;     /* remount from flash */
    if (flashfs_get(&fs, 1, v, sizeof(v), &n) != FLASHFS_OK || n != 15 || !bytes_equal(v, b, 15)) return 10;
    return 0;
}

/* A non-identity test service (+1 to each byte): used to prove the HECI layer
 * actually dispatches delivered messages to the service and sends what it
 * returns, rather than echoing internally. */
static size_t inc_handle(const uint8_t *in, size_t n, uint8_t *out, size_t cap)
{
    size_t i;
    if (n > cap) n = cap;
    for (i = 0; i < n; ++i) out[i] = (uint8_t)(in[i] + 1);
    return n;
}
static const struct om_service inc_service = { "test.inc", {0}, inc_handle };

/* Play the host for one packet: hand it to the HAL, then let the firmware
 * service loop move it through and emit any reply. */
static void convo_step(struct om_firmware *fw, const uint8_t *pkt, size_t len)
{
    om_model_host_send(pkt, len);
    om_firmware_service(fw, 16);
}
static void convo_drain(void)
{
    uint8_t b[OM_HECI_PACKET];
    size_t n;
    while (om_model_host_recv(b, sizeof(b), &n) == OM_HAL_OK) { }
}

/* --- interactive filesystem-explorer helpers (dev shell only) --- */
static int starts_with(const char *s, const char *p)
{
    while (*p) { if (*s != *p) return 0; ++s; ++p; }
    return 1;
}
static const char *skip_spaces(const char *s)
{
    while (*s == ' ') ++s;
    return s;
}
static const char *parse_dec(const char *s, int *out)
{
    int v = 0, any = 0;
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); if (v > 255) v = 255; ++s; any = 1; }
    if (!any) return 0;
    *out = v;
    return s;
}
static void print_dec(unsigned v)
{
    char buf[10];
    int i = 0;
    if (!v) { putch('0'); return; }
    while (v) { buf[i++] = (char)('0' + v % 10); v /= 10; }
    while (i) putch(buf[--i]);
}
static void print_value(const uint8_t *v, size_t n)
{
    size_t i;
    for (i = 0; i < n; ++i) putch((v[i] >= 32 && v[i] <= 126) ? (char)v[i] : '.');
}
/* Open the emulated flash as a filesystem (mount, or format if blank). */
static int dev_fs_open(struct flashfs *fs)
{
    struct flash_dev d;
    flashfs_ram_backend(&d);
    if (flashfs_mount(fs, &d) == FLASHFS_OK) return 1;
    return flashfs_format(fs, &d) == FLASHFS_OK;
}

static void command(void)
{
    if (equal(line, "help")) {
        puts_serial("files: ls | cat FILE | echo TEXT > FILE | rm FILE | format\n");
        puts_serial("tools: boot run convo gate persist platform hal fs time status version | frame HEX | heci HEX | heci-poll | heci-reset | halt\n");
    }
    else if (equal(line, "time")) {
        uint32_t t0 = PLATFORM_HAL.ticks();
        uint32_t t1 = PLATFORM_HAL.ticks();
        puts_serial("time: advancing=");
        puts_serial(t1 > t0 ? "yes" : "no");
        puts_serial("\n");
    }
    else if (equal(line, "boot")) {
        /* Run the full firmware bring-up against the emulation HAL + flash. */
        static struct om_firmware fw;
        struct om_boot_report r;
        struct flash_dev flash;
        struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };
        flashfs_ram_backend(&flash);
        om_firmware_boot(&fw, &om_hal_model, id, &flash, &r);
        puts_serial("boot: platform="); puts_serial(r.platform_name);
        puts_serial("("); puts_serial(om_support_name(r.support)); puts_serial(")");
        puts_serial(" hal="); puts_serial(om_hal_status_name(r.hal_bringup));
        puts_serial(" fs="); puts_serial(flashfs_status_name(r.fs_status));
        if (r.fs_formatted) puts_serial("(formatted)");
        puts_serial(" heci="); puts_serial(r.heci_ready ? "ready" : "down");
        puts_serial(" net="); puts_serial(r.network ? "ENABLED" : "none");
        puts_serial(" result="); puts_serial(r.ok ? "ok" : "fail");
        puts_serial("\n");
    }
    else if (equal(line, "platform")) {
        /* This QEMU build is the emulation target. A real build would pass the
         * chipset/ME generation detected by its HAL instead of this constant. */
        const char *name = "", *reason = "";
        struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };
        enum om_support s = om_platform_check(id, &name, &reason);
        puts_serial("platform="); puts_serial(name);
        puts_serial(" support="); puts_serial(om_support_name(s));
        if (s != OM_SUPPORT_OK) { puts_serial(" WARNING: "); puts_serial(reason); }
        puts_serial("\n");
    }
    else if (equal(line, "version")) puts_serial("OpenME 0.1; target=qemu-pc-i386; transport=framed-v1,hbm-1.0-packet-test\n");
    else if (equal(line, "hal")) {
        /* Exercise the HAL seam in both directions: host->ME via recv, and
         * ME->host via send, using the model HAL's host-side hooks. */
        uint8_t a[4] = {0xde, 0xad, 0xbe, 0xef}, ra[4];
        uint8_t b[3] = {1, 2, 3}, rb[3];
        size_t ga = 0, gb = 0;
        enum om_hal_status bs = PLATFORM_HAL.bringup();
        int h2m = om_model_host_send(a, sizeof(a)) == OM_HAL_OK &&
                  PLATFORM_HAL.recv(ra, sizeof(ra), &ga) == OM_HAL_OK &&
                  ga == sizeof(a) && bytes_equal(ra, a, sizeof(a));
        int m2h = PLATFORM_HAL.send(b, sizeof(b)) == OM_HAL_OK &&
                  om_model_host_recv(rb, sizeof(rb), &gb) == OM_HAL_OK &&
                  gb == sizeof(b) && bytes_equal(rb, b, sizeof(b));
        puts_serial("hal="); puts_serial(PLATFORM_HAL.name);
        puts_serial(" gen="); puts_serial(PLATFORM_HAL.me_generation);
        puts_serial(" bringup="); puts_serial(om_hal_status_name(bs));
        puts_serial(" h2m="); puts_serial(h2m ? "ok" : "fail");
        puts_serial(" m2h="); puts_serial(m2h ? "ok" : "fail");
        puts_serial("\n");
    }
    else if (equal(line, "run")) {
        /* Autonomous service: play the host, inject one HBM HOST_START, let the
         * firmware's service loop move it HAL->HECI and the reply HECI->HAL,
         * then read the reply back as the host. End-to-end through the HAL seam,
         * with no hand-feeding of the protocol layer. */
        static struct om_firmware fw;
        struct om_boot_report r;
        struct flash_dev flash;
        struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };
        static const uint8_t host_start[8] = {0x00, 0x00, 0x04, 0x80, 0x01, 0x00, 0x02, 0x02};
        static const uint8_t expect[8]     = {0x00, 0x00, 0x04, 0x80, 0x81, 0x00, 0x00, 0x01};
        uint8_t reply[OM_HECI_PACKET];
        size_t n = 0;
        int ok;
        flashfs_ram_backend(&flash);
        om_firmware_boot(&fw, &om_hal_model, id, &flash, &r);
        om_firmware_power(&fw, 1);                           /* machine powered on */
        om_model_host_send(host_start, sizeof(host_start)); /* act as the host */
        om_firmware_service(&fw, 16);                       /* firmware services the ring */
        ok = r.ok && om_model_host_recv(reply, sizeof(reply), &n) == OM_HAL_OK &&
             n == sizeof(expect) && bytes_equal(reply, expect, sizeof(expect));
        puts_serial("run: boot="); puts_serial(r.ok ? "ok" : "fail");
        puts_serial(" host-start="); puts_serial(ok ? "ok" : "fail");
        puts_serial("\n");
    }
    else if (equal(line, "convo")) {
        /* Full autonomous conversation proving service dispatch: host-start ->
         * connect -> data -> grant, with a +1 transform service registered.
         * The data the host gets back must be its bytes + 1, which can only
         * happen if the HECI layer actually called the service. */
        static struct om_firmware fw;
        struct om_boot_report r;
        struct flash_dev flash;
        struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };
        static const uint8_t host_start[8] = {0, 0, 4, 0x80, 0x01, 0x00, 0x02, 0x02};
        static const uint8_t connect[8]    = {0, 0, 4, 0x80, 0x06, 0x07, 0x03, 0x00};
        static const uint8_t data[8]       = {0x07, 0x03, 4, 0x80, 0x57, 0x58, 0x59, 0x5a};
        static const uint8_t grant[12]     = {0, 0, 8, 0x80, 0x08, 0x07, 0x03, 0x00, 0, 0, 0, 0};
        static const uint8_t expect[8]     = {0x07, 0x03, 4, 0x80, 0x58, 0x59, 0x5a, 0x5b};
        uint8_t rx[OM_HECI_PACKET];
        size_t n = 0;
        int ok;
        flashfs_ram_backend(&flash);
        om_firmware_boot(&fw, &om_hal_model, id, &flash, &r);
        fw.heci.service = &inc_service;
        om_firmware_power(&fw, 1);
        convo_step(&fw, host_start, sizeof(host_start)); convo_drain();
        convo_step(&fw, connect, sizeof(connect)); convo_drain();
        convo_step(&fw, data, sizeof(data));   /* buffered + transformed, no reply yet */
        convo_step(&fw, grant, sizeof(grant)); /* host grants read credit -> reply */
        ok = r.ok && om_model_host_recv(rx, sizeof(rx), &n) == OM_HAL_OK &&
             n == sizeof(expect) && bytes_equal(rx, expect, sizeof(expect));
        puts_serial("convo: service-dispatch="); puts_serial(ok ? "ok" : "fail");
        puts_serial("\n");
    }
    else if (equal(line, "gate")) {
        /* Dormant-by-default proof: a host message sent while the system is off
         * gets NO response; after power-on, the same queued message is serviced. */
        static struct om_firmware fw;
        struct om_boot_report r;
        struct flash_dev flash;
        struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };
        static const uint8_t host_start[8] = {0, 0, 4, 0x80, 0x01, 0x00, 0x02, 0x02};
        uint8_t rx[OM_HECI_PACKET];
        size_t n = 0;
        int dormant_ok, active_ok;
        flashfs_ram_backend(&flash);
        om_firmware_boot(&fw, &om_hal_model, id, &flash, &r); /* boots dormant */
        om_model_host_send(host_start, sizeof(host_start));
        om_firmware_service(&fw, 16);                         /* dormant: does nothing */
        dormant_ok = om_model_host_recv(rx, sizeof(rx), &n) == OM_HAL_EMPTY;
        om_firmware_power(&fw, 1);                            /* power button pressed */
        om_firmware_service(&fw, 16);                         /* now it services */
        active_ok = om_model_host_recv(rx, sizeof(rx), &n) == OM_HAL_OK && n == 8;
        puts_serial("gate: dormant="); puts_serial(dormant_ok ? "ok" : "fail");
        puts_serial(" active="); puts_serial(active_ok ? "ok" : "fail");
        puts_serial("\n");
    }
    else if (equal(line, "persist")) {
        /* Reboot persistence: boot three times on the SAME retained flash; the
         * boot counter stored in the filesystem must carry over (1 -> 2 -> 3).
         * This is warm persistence (the flash medium is retained); cold
         * process-restart persistence via a file-backed flash is separate. */
        static struct om_firmware fw;
        struct om_boot_report r;
        struct flash_dev flash;
        struct om_platform_id id = { OM_CHIPSET_EMULATION, 0 };
        struct flashfs clean;
        uint32_t c1, c2, c3;
        int ok;
        flashfs_ram_backend(&flash);
        flashfs_format(&clean, &flash); /* deterministic clean medium for the demo */
        om_firmware_boot(&fw, &om_hal_model, id, &flash, &r); c1 = r.boot_count;
        om_firmware_boot(&fw, &om_hal_model, id, &flash, &r); c2 = r.boot_count; /* reboot */
        om_firmware_boot(&fw, &om_hal_model, id, &flash, &r); c3 = r.boot_count; /* reboot */
        ok = (c1 == 1 && c2 == 2 && c3 == 3);
        puts_serial("persist: boot-count=");
        putch((char)('0' + (c1 % 10))); putch(',');
        putch((char)('0' + (c2 % 10))); putch(',');
        putch((char)('0' + (c3 % 10)));
        puts_serial(ok ? " survives-reboot=ok" : " survives-reboot=fail");
        puts_serial("\n");
    }
    else if (equal(line, "ls")) {
        struct flashfs fs;
        if (!dev_fs_open(&fs)) puts_serial("fs error\n");
        else {
            int k, found = 0;
            for (k = 0; k < 256; ++k) {
                uint8_t v[FLASHFS_MAX_VALUE];
                uint32_t n = 0;
                if (flashfs_get(&fs, (uint8_t)k, v, sizeof(v), &n) == FLASHFS_OK) {
                    found = 1;
                    print_dec((unsigned)k); puts_serial("  "); print_dec(n); puts_serial(" bytes\n");
                }
            }
            if (!found) puts_serial("(no files)\n");
        }
    }
    else if (starts_with(line, "cat ")) {
        const char *p = skip_spaces(line + 4);
        int k;
        p = parse_dec(p, &k);
        if (!p) puts_serial("usage: cat FILE\n");
        else {
            struct flashfs fs;
            uint8_t v[FLASHFS_MAX_VALUE];
            uint32_t n = 0;
            if (!dev_fs_open(&fs)) puts_serial("fs error\n");
            else if (flashfs_get(&fs, (uint8_t)k, v, sizeof(v), &n) == FLASHFS_OK) {
                print_value(v, n); puts_serial("\n");
            }
            else puts_serial("cat: no such file\n");
        }
    }
    else if (starts_with(line, "rm ")) {
        const char *p = skip_spaces(line + 3);
        int k;
        p = parse_dec(p, &k);
        if (!p) puts_serial("usage: rm FILE\n");
        else {
            struct flashfs fs;
            if (!dev_fs_open(&fs)) puts_serial("fs error\n");
            else puts_serial(flashfs_delete(&fs, (uint8_t)k) == FLASHFS_OK ? "removed\n" : "rm: no such file\n");
        }
    }
    else if (starts_with(line, "echo ")) {
        const char *p = line + 5, *gt = 0, *s = p;
        while (*s) { if (s[0] == ' ' && s[1] == '>' && s[2] == ' ') { gt = s; break; } ++s; }
        if (!gt) { puts_serial(p); puts_serial("\n"); } /* plain echo */
        else {
            int k;
            const char *fp = parse_dec(skip_spaces(gt + 3), &k);
            if (!fp) puts_serial("usage: echo TEXT > FILE\n");
            else {
                size_t len = (size_t)(gt - p);
                struct flashfs fs;
                if (len > FLASHFS_MAX_VALUE) len = FLASHFS_MAX_VALUE;
                if (!dev_fs_open(&fs)) puts_serial("fs error\n");
                else puts_serial(flashfs_set(&fs, (uint8_t)k, (const uint8_t *)p, (uint32_t)len) == FLASHFS_OK
                                 ? "written\n" : "echo: write failed\n");
            }
        }
    }
    else if (equal(line, "format")) {
        struct flashfs fs;
        struct flash_dev d;
        flashfs_ram_backend(&d);
        puts_serial(flashfs_format(&fs, &d) == FLASHFS_OK ? "formatted\n" : "format failed\n");
    }
    else if (equal(line, "fs")) {
        int step = fs_selftest();
        if (!step) puts_serial("fs=flashfs selftest=ok\n");
        else {
            puts_serial("fs=flashfs selftest=fail step=");
            putch((char)('0' + step / 10));
            putch((char)('0' + step % 10));
            puts_serial("\n");
        }
    }
    else if (equal(line, "status")) {
        puts_serial("state="); puts_serial(om_state_name(core.state)); puts_serial("\n");
    } else if (equal(line, "heci-poll")) {
        size_t n = om_heci_transmit(&heci, response, sizeof(response));
        if (!n) puts_serial("heci empty\n");
        else { puts_serial("heci reply "); print_hex(response, n); }
    } else if (equal(line, "heci-reset")) {
        om_heci_reset(&heci);
        puts_serial("heci reset\n");
    } else if (equal(line, "halt")) {
        puts_serial("OpenME halted\n");
        /* QEMU isa-debug-exit, configured by the test runner. */
        out8(0xf4, 0x10);
        for (;;) __asm__ volatile ("cli; hlt");
    } else if (line[0] == 'f' && line[1] == 'r' && line[2] == 'a' &&
               line[3] == 'm' && line[4] == 'e' && line[5] == ' ') frame(line + 6, 0);
    else if (line[0] == 'h' && line[1] == 'e' && line[2] == 'c' &&
             line[3] == 'i' && line[4] == ' ') frame(line + 5, 1);
    else if (line[0]) puts_serial("error: unknown command\n");
}

void firmware_main(uint32_t boot_magic)
{
    size_t used = 0;
    int discard = 0, previous_cr = 0;
    out8(UART + 1, 0); out8(UART + 3, 0x80);
    out8(UART, 1); out8(UART + 1, 0);
    out8(UART + 3, 3); out8(UART + 2, 0xc7); out8(UART + 4, 0x0b);
    if (boot_magic != 0x2badb002) {
        puts_serial("fault: invalid Multiboot handoff\n");
        out8(0xf4, 0x11);
        for (;;) __asm__ volatile ("cli; hlt");
    }
    om_init(&core);
    om_heci_reset(&heci);
    puts_serial("OpenME 0.1 - source-built firmware / QEMU PC test target\nopenme:/# ");
    for (;;) {
        char c;
        if (!(in8(UART + 5) & 1)) continue;
        c = (char)in8(UART);
        if (c == '\n' && previous_cr) { previous_cr = 0; continue; }
        previous_cr = c == '\r';
        if (c == '\r' || c == '\n') {
            puts_serial("\n"); line[used] = 0;
            if (discard) puts_serial("error: line too long\n");
            else command();
            used = 0; discard = 0; puts_serial("openme:/# ");
        } else if (!discard && (c == '\b' || c == 127)) {
            if (used) { --used; puts_serial("\b \b"); }
        } else if (c >= 32 && c <= 126) {
            if (used == sizeof(line) - 1) discard = 1;
            else if (!discard) line[used++] = c;
            /* Echo also acknowledges consumed input after overflow; discard
             * remains latched until newline, so no suffix becomes a command. */
            putch(c);
        }
    }
}
