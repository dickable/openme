/* SPDX-License-Identifier: MIT */
#ifndef OPENME_FLASHFS_H
#define OPENME_FLASHFS_H

#include <stddef.h>
#include <stdint.h>

/*
 * OpenME embedded flash filesystem — the project's own EFFS/MFS-equivalent.
 *
 * The real ME stores its persistent config/keys/state in an on-flash
 * filesystem (EFFS on the ARC generations, MFS later). A from-scratch ME needs
 * the same capability. This is OpenME's OWN design — it is not a parser of
 * Intel's undocumented format and claims no compatibility with it.
 *
 * It is a log-structured key->value store built for raw NOR flash semantics:
 *   - erase sets a whole sector to 0xFF (all bits 1);
 *   - program may only clear bits (1 -> 0); it can never set a 0 bit back to 1;
 *   - so updates are appended, superseded records are marked dead by clearing
 *     a state byte, and a full sector is compacted into a spare one.
 * Freestanding, no libc, no allocator; all buffers are bounded and static.
 */

enum flashfs_status {
    FLASHFS_OK = 0,
    FLASHFS_NOT_FOUND,
    FLASHFS_NO_SPACE,
    FLASHFS_TOO_LARGE,
    FLASHFS_CORRUPT,  /* no valid sector header found; caller should format */
    FLASHFS_IO,       /* backend rejected a read/program/erase */
    FLASHFS_INVALID   /* bad arguments or not mounted */
};

/*
 * NOR flash backend. A real port supplies these from the ME's flash
 * controller; the emulation backend (nor_model.c) models the same rules over
 * RAM and rejects any program that would set a cleared bit back to 1.
 */
struct flash_dev {
    enum flashfs_status (*read)(void *ctx, uint32_t off, uint8_t *buf, uint32_t len);
    enum flashfs_status (*program)(void *ctx, uint32_t off, const uint8_t *buf, uint32_t len);
    enum flashfs_status (*erase)(void *ctx, uint32_t sector);
    void *ctx;
    uint32_t sector_size;  /* bytes per erase unit */
    uint32_t sector_count; /* total sectors; >= 2 for compaction */
};

#define FLASHFS_MAX_VALUE 64u /* bounded record payload (no allocator) */

struct flashfs {
    struct flash_dev dev;
    uint32_t active;  /* index of the active (log) sector */
    uint32_t gen;     /* generation of the active sector (newest wins on mount) */
    uint32_t cursor;  /* next free byte offset within the active sector */
    uint8_t mounted;
};

/* Format (erase everything, start a fresh log) or mount an existing store. */
enum flashfs_status flashfs_format(struct flashfs *fs, const struct flash_dev *dev);
enum flashfs_status flashfs_mount(struct flashfs *fs, const struct flash_dev *dev);

/* key is a small id (0..255). Value is at most FLASHFS_MAX_VALUE bytes. */
enum flashfs_status flashfs_set(struct flashfs *fs, uint8_t key,
                                const uint8_t *val, uint32_t len);
enum flashfs_status flashfs_get(struct flashfs *fs, uint8_t key,
                                uint8_t *buf, uint32_t cap, uint32_t *out_len);
enum flashfs_status flashfs_delete(struct flashfs *fs, uint8_t key);

const char *flashfs_status_name(enum flashfs_status status);

/* Emulation backend: a RAM-backed NOR model enforcing erase/program rules. */
void flashfs_ram_backend(struct flash_dev *dev);

/* Emulation NOR snapshot (host-backed cold-persistence tests): seed the model
 * from an image, read it back out, and query its size. */
void om_nor_load(const uint8_t *src, uint32_t n);
uint32_t om_nor_save(uint8_t *dst, uint32_t cap);
uint32_t om_nor_total(void);

#endif
