/* SPDX-License-Identifier: MIT */
#include "../../src/firmware.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static enum flashfs_status reject_write(void *ctx, uint32_t off, const uint8_t *buf, uint32_t len)
{
    (void)ctx; (void)off; (void)buf; (void)len;
    return FLASHFS_IO;
}
int main(void)
{
    struct om_firmware fw;
    struct om_boot_report report;
    struct flash_dev flash, broken;
    struct flashfs fs;
    struct om_platform_id id = {OM_CHIPSET_EMULATION, 0};
    uint8_t seed[2048], next[2048], check[2050], val[4], short_image[3] = {0x12, 0, 0x34};
    uint32_t length = 0;
    assert(om_nor_total() == sizeof(seed));
    memset(check, 0x5a, sizeof(check));
    assert(om_nor_save(check + 1, sizeof(seed)) == sizeof(seed));
    assert(check[0] == 0x5a && check[2049] == 0x5a);
    for (unsigned i = 1; i <= 2048; ++i) assert(check[i] == 0xff);
    om_nor_load(short_image, sizeof(short_image));
    assert(om_nor_save(seed, sizeof(seed)) == sizeof(seed));
    assert(!memcmp(seed, short_image, sizeof(short_image)));
    for (unsigned i = 3; i < sizeof(seed); ++i) assert(seed[i] == 0xff);
    memset(check, 0xa5, sizeof(check));
    assert(om_nor_save(check + 1, 2) == 2);
    assert(check[0] == 0xa5 && check[1] == 0x12 && check[2] == 0 && check[3] == 0xa5);
    om_nor_load(NULL, 0); /* defined zero-length seed: erased NOR */
    flashfs_ram_backend(&flash);
    assert(om_firmware_boot(&fw, &om_hal_model, id, &flash, &report));
    assert(report.boot_count == 1 && report.fs_formatted && !report.network && !fw.powered);
    assert(om_nor_save(seed, sizeof(seed)) == sizeof(seed));
    om_nor_load(NULL, 0); /* discard model state before restoring serialized bytes */
    om_nor_load(seed, sizeof(seed));
    memset(&fw, 0, sizeof(fw));
    assert(om_firmware_boot(&fw, &om_hal_model, id, &flash, &report));
    assert(report.boot_count == 2 && !report.fs_formatted && !fw.powered);
    assert(flashfs_get(&fw.fs, 0, val, 4, &length) == FLASHFS_OK);
    assert(length == 4 && val[0] == 2 && !val[1] && !val[2] && !val[3]);
    assert(om_nor_save(next, sizeof(next)) == sizeof(next));
    assert(memcmp(seed, next, sizeof(seed)));
    /* Snapshot restoration doesn't relax NOR's 1->0-only programming rule. */
    val[0] = 0xff;
    assert(flash.program(flash.ctx, 0, val, 1) == FLASHFS_IO);
    broken = flash; broken.program = reject_write;
    fw.powered = 1;
    assert(!om_firmware_boot(&fw, &om_hal_model, id, &broken, &report));
    assert(report.fs_status == FLASHFS_IO && !report.ok && !report.heci_ready);
    assert(!report.boot_count && !fw.powered);
    om_nor_save(check, sizeof(check));
    assert(!memcmp(next, check, sizeof(next)));
    /* Corrupt, wrongly-sized, or overflowing counters must not silently reset. */
    for (unsigned scenario = 0; scenario < 3; ++scenario) {
        om_nor_load(seed, sizeof(seed));
        assert(flashfs_mount(&fs, &flash) == FLASHFS_OK);
        memset(val, 0xff, sizeof(val));
        if (scenario == 0) {
            om_nor_save(check, sizeof(check));
            check[16] ^= 0x40; /* first record's counter payload, without updating CRC */
            om_nor_load(check, 2048);
        } else {
            assert(flashfs_set(&fs, 0, val, scenario == 1 ? 3 : 4) == FLASHFS_OK);
        }
        om_nor_save(next, sizeof(next));
        assert(!om_firmware_boot(&fw, &om_hal_model, id, &flash, &report));
        assert(!report.ok && !report.boot_count && !report.heci_ready);
        om_nor_save(check, sizeof(check));
        assert(!memcmp(next, check, sizeof(next)));
    }
    puts("NOR snapshots, counter persistence, and failed-save regressions passed");
    return 0;
}
