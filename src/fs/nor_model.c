/* SPDX-License-Identifier: MIT */
#include "flashfs.h"

/*
 * Emulation NOR-flash backend.
 *
 * A RAM array that behaves like real NOR flash: erase sets a sector to all
 * 0xFF, and program may only CLEAR bits. A program that tried to set a bit
 * from 0 back to 1 is rejected with FLASHFS_IO, so a filesystem bug that
 * "rewrites in place" is caught here instead of silently working in RAM and
 * failing on real hardware.
 */
#define NOR_SECTOR_SIZE 1024u
#define NOR_SECTORS     2u

static uint8_t nor[NOR_SECTORS * NOR_SECTOR_SIZE];
static int nor_initialized;

static void nor_init(void)
{
    uint32_t i;
    for (i = 0; i < sizeof(nor); ++i) nor[i] = 0xFF;
    nor_initialized = 1;
}

static enum flashfs_status nor_read(void *ctx, uint32_t off, uint8_t *buf, uint32_t len)
{
    uint32_t i;
    (void)ctx;
    if (!nor_initialized) nor_init();
    if (off + len > sizeof(nor) || off + len < off) return FLASHFS_IO;
    for (i = 0; i < len; ++i) buf[i] = nor[off + i];
    return FLASHFS_OK;
}

static enum flashfs_status nor_program(void *ctx, uint32_t off, const uint8_t *buf, uint32_t len)
{
    uint32_t i;
    (void)ctx;
    if (!nor_initialized) nor_init();
    if (off + len > sizeof(nor) || off + len < off) return FLASHFS_IO;
    /* NOR can only clear bits. Setting a 0 bit back to 1 is impossible. */
    for (i = 0; i < len; ++i)
        if (buf[i] & ~nor[off + i]) return FLASHFS_IO;
    for (i = 0; i < len; ++i) nor[off + i] &= buf[i];
    return FLASHFS_OK;
}

static enum flashfs_status nor_erase(void *ctx, uint32_t sector)
{
    uint32_t i, base;
    (void)ctx;
    if (!nor_initialized) nor_init();
    if (sector >= NOR_SECTORS) return FLASHFS_IO;
    base = sector * NOR_SECTOR_SIZE;
    for (i = 0; i < NOR_SECTOR_SIZE; ++i) nor[base + i] = 0xFF;
    return FLASHFS_OK;
}

void flashfs_ram_backend(struct flash_dev *dev)
{
    dev->read = nor_read;
    dev->program = nor_program;
    dev->erase = nor_erase;
    dev->ctx = 0;
    dev->sector_size = NOR_SECTOR_SIZE;
    dev->sector_count = NOR_SECTORS;
}

void om_nor_load(const uint8_t *src, uint32_t n)
{
    uint32_t i;
    nor_initialized = 1;
    for (i = 0; i < sizeof(nor); ++i)
        nor[i] = (i < n) ? src[i] : 0xFF;
}

uint32_t om_nor_save(uint8_t *dst, uint32_t cap)
{
    uint32_t i, n = cap < (uint32_t)sizeof(nor) ? cap : (uint32_t)sizeof(nor);
    if (!nor_initialized) nor_init();
    for (i = 0; i < n; ++i) dst[i] = nor[i];
    return n;
}

uint32_t om_nor_total(void)
{
    return (uint32_t)sizeof(nor);
}
