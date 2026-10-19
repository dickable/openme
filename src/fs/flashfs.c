/* SPDX-License-Identifier: MIT */
#include "flashfs.h"

/*
 * On-flash layout, per sector:
 *
 *   [ sector header: 8 bytes ]   SH_MAGIC + 32-bit generation
 *   [ record ][ record ] ...     appended; free space reads back as 0xFF
 *
 * Record (8-byte header + value):
 *   off 0: magic   (2)  REC_MAGIC; 0xFFFF means erased/free -> end of log
 *   off 2: key     (1)
 *   off 3: state   (1)  0xFF = live, 0x00 = dead (only a 1->0 clear is legal)
 *   off 4: len     (2)
 *   off 6: crc16   (2)  over key, len, value
 *   off 8: value   (len)
 *
 * "Latest live record for a key wins", so even if a crash leaves both an old
 * and a new record live, reads still return the newest. Marking the old record
 * dead is only a space optimization.
 */
#define SEC_HDR   8u
#define REC_HDR   8u
#define SH_MAGIC  0x4653u /* 'S','F' */
#define REC_MAGIC 0x4F46u /* 'F','O' */
#define ST_LIVE   0xFFu
#define ST_DEAD   0x00u
#define ERASED16  0xFFFFu

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static void wr16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void wr32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static uint16_t crc16(uint16_t c, const uint8_t *p, uint32_t n)
{
    for (uint32_t i = 0; i < n; ++i) {
        c ^= (uint16_t)((uint16_t)p[i] << 8);
        for (int b = 0; b < 8; ++b)
            c = (c & 0x8000u) ? (uint16_t)((c << 1) ^ 0x1021u) : (uint16_t)(c << 1);
    }
    return c;
}

static enum flashfs_status rd(struct flashfs *fs, uint32_t off, uint8_t *b, uint32_t n)
{
    return fs->dev.read(fs->dev.ctx, off, b, n);
}
static enum flashfs_status pr(struct flashfs *fs, uint32_t off, const uint8_t *b, uint32_t n)
{
    return fs->dev.program(fs->dev.ctx, off, b, n);
}

static uint16_t record_crc(uint8_t key, uint32_t len, const uint8_t *val)
{
    uint8_t meta[3];
    meta[0] = key; meta[1] = (uint8_t)len; meta[2] = (uint8_t)(len >> 8);
    return crc16(crc16(0xFFFFu, meta, 3), val, len);
}

/* Walk a sector's records. Returns the offset of the newest live record with
 * `key` (or -1 if none), and writes the first free offset to *end. */
static int32_t walk(struct flashfs *fs, uint32_t sector, int match, uint8_t key, uint32_t *end)
{
    uint32_t ss = fs->dev.sector_size, base = sector * ss, rel = SEC_HDR;
    int32_t best = -1;
    for (;;) {
        uint8_t h[REC_HDR];
        uint16_t len;
        if (rel + REC_HDR > ss) break;
        if (rd(fs, base + rel, h, REC_HDR) != FLASHFS_OK) break;
        if (rd16(h) == ERASED16) break;  /* reached erased free space */
        if (rd16(h) != REC_MAGIC) break; /* corruption: stop the scan here */
        len = rd16(h + 4);
        if (len > FLASHFS_MAX_VALUE || rel + REC_HDR + len > ss) break;
        if (match && h[2] == key && h[3] == ST_LIVE)
            best = (int32_t)rel; /* keep scanning: latest wins */
        rel += REC_HDR + len;
    }
    if (end) *end = rel;
    return best;
}

static enum flashfs_status write_sector_header(struct flashfs *fs, uint32_t sector, uint32_t gen)
{
    uint8_t h[SEC_HDR];
    wr16(h, SH_MAGIC);
    wr32(h + 2, gen);
    h[6] = h[7] = 0xFF; /* reserved; left in the erased state */
    return pr(fs, sector * fs->dev.sector_size, h, SEC_HDR);
}

static enum flashfs_status write_record(struct flashfs *fs, uint32_t sector, uint32_t rel,
                                        uint8_t key, const uint8_t *val, uint32_t len)
{
    uint8_t buf[REC_HDR + FLASHFS_MAX_VALUE];
    uint32_t i;
    if (len > FLASHFS_MAX_VALUE) return FLASHFS_TOO_LARGE;
    wr16(buf, REC_MAGIC);
    buf[2] = key;
    buf[3] = ST_LIVE;
    wr16(buf + 4, (uint16_t)len);
    wr16(buf + 6, record_crc(key, len, val));
    for (i = 0; i < len; ++i) buf[REC_HDR + i] = val[i];
    return pr(fs, sector * fs->dev.sector_size + rel, buf, REC_HDR + len);
}

/* Clear the state byte of a live record to mark it dead (1->0, always legal). */
static enum flashfs_status kill_record(struct flashfs *fs, uint32_t sector, uint32_t rel)
{
    uint8_t dead = ST_DEAD;
    return pr(fs, sector * fs->dev.sector_size + rel + 3, &dead, 1);
}

static enum flashfs_status erase_sector(struct flashfs *fs, uint32_t sector)
{
    return fs->dev.erase(fs->dev.ctx, sector);
}

enum flashfs_status flashfs_format(struct flashfs *fs, const struct flash_dev *dev)
{
    uint32_t s;
    if (!fs || !dev || dev->sector_count < 2 || dev->sector_size < SEC_HDR + REC_HDR)
        return FLASHFS_INVALID;
    fs->dev = *dev;
    for (s = 0; s < dev->sector_count; ++s)
        if (erase_sector(fs, s) != FLASHFS_OK) return FLASHFS_IO;
    if (write_sector_header(fs, 0, 1) != FLASHFS_OK) return FLASHFS_IO;
    fs->active = 0;
    fs->gen = 1;
    fs->cursor = SEC_HDR;
    fs->mounted = 1;
    return FLASHFS_OK;
}

enum flashfs_status flashfs_mount(struct flashfs *fs, const struct flash_dev *dev)
{
    uint32_t s, best_gen = 0;
    int found = 0;
    if (!fs || !dev || dev->sector_count < 2 || dev->sector_size < SEC_HDR + REC_HDR)
        return FLASHFS_INVALID;
    fs->dev = *dev;
    for (s = 0; s < dev->sector_count; ++s) {
        uint8_t h[SEC_HDR];
        uint32_t gen;
        if (rd(fs, s * dev->sector_size, h, SEC_HDR) != FLASHFS_OK) return FLASHFS_IO;
        if (rd16(h) != SH_MAGIC) continue;
        gen = rd32(h + 2);
        if (!found || gen > best_gen) { best_gen = gen; fs->active = s; found = 1; }
    }
    if (!found) return FLASHFS_CORRUPT;
    fs->gen = best_gen;
    walk(fs, fs->active, 0, 0, &fs->cursor);
    fs->mounted = 1;
    return FLASHFS_OK;
}

/* Copy the newest live value of every key into a freshly erased spare sector. */
static enum flashfs_status compact(struct flashfs *fs)
{
    uint32_t target = (fs->active + 1) % fs->dev.sector_count;
    uint32_t tcur = SEC_HDR;
    int k;
    if (erase_sector(fs, target) != FLASHFS_OK) return FLASHFS_IO;
    if (write_sector_header(fs, target, fs->gen + 1) != FLASHFS_OK) return FLASHFS_IO;
    for (k = 0; k < 256; ++k) {
        uint8_t h[REC_HDR], val[FLASHFS_MAX_VALUE];
        int32_t rel = walk(fs, fs->active, 1, (uint8_t)k, NULL);
        uint32_t base = fs->active * fs->dev.sector_size, len;
        if (rel < 0) continue;
        if (rd(fs, base + (uint32_t)rel, h, REC_HDR) != FLASHFS_OK) return FLASHFS_IO;
        len = rd16(h + 4);
        if (len > FLASHFS_MAX_VALUE) return FLASHFS_CORRUPT;
        if (rd(fs, base + (uint32_t)rel + REC_HDR, val, len) != FLASHFS_OK) return FLASHFS_IO;
        if (tcur + REC_HDR + len > fs->dev.sector_size) return FLASHFS_NO_SPACE;
        if (write_record(fs, target, tcur, (uint8_t)k, val, len) != FLASHFS_OK) return FLASHFS_IO;
        tcur += REC_HDR + len;
    }
    fs->active = target;
    fs->gen += 1;
    fs->cursor = tcur;
    return FLASHFS_OK;
}

enum flashfs_status flashfs_set(struct flashfs *fs, uint8_t key,
                                const uint8_t *val, uint32_t len)
{
    uint32_t need, newrel, rel;
    uint32_t ss;
    if (!fs || !fs->mounted || (!val && len)) return FLASHFS_INVALID;
    if (len > FLASHFS_MAX_VALUE) return FLASHFS_TOO_LARGE;
    ss = fs->dev.sector_size;
    need = REC_HDR + len;
    if (fs->cursor + need > ss) {
        enum flashfs_status rc = compact(fs);
        if (rc != FLASHFS_OK) return rc;
        if (fs->cursor + need > ss) return FLASHFS_NO_SPACE;
    }
    newrel = fs->cursor;
    if (write_record(fs, fs->active, newrel, key, val, len) != FLASHFS_OK) return FLASHFS_IO;
    fs->cursor = newrel + need;
    /* Retire older live copies of this key (space reclaim; reads are safe
     * regardless because the newest live record is at the highest offset). */
    for (rel = SEC_HDR; rel < newrel; ) {
        uint8_t h[REC_HDR];
        uint16_t rlen;
        if (rd(fs, fs->active * ss + rel, h, REC_HDR) != FLASHFS_OK) break;
        if (rd16(h) != REC_MAGIC) break;
        rlen = rd16(h + 4);
        if (rlen > FLASHFS_MAX_VALUE) break;
        if (h[2] == key && h[3] == ST_LIVE)
            kill_record(fs, fs->active, rel);
        rel += REC_HDR + rlen;
    }
    return FLASHFS_OK;
}

enum flashfs_status flashfs_get(struct flashfs *fs, uint8_t key,
                                uint8_t *buf, uint32_t cap, uint32_t *out_len)
{
    uint8_t h[REC_HDR];
    uint32_t base, len;
    int32_t rel;
    if (!fs || !fs->mounted || !buf || !out_len) return FLASHFS_INVALID;
    rel = walk(fs, fs->active, 1, key, NULL);
    if (rel < 0) return FLASHFS_NOT_FOUND;
    base = fs->active * fs->dev.sector_size;
    if (rd(fs, base + (uint32_t)rel, h, REC_HDR) != FLASHFS_OK) return FLASHFS_IO;
    len = rd16(h + 4);
    if (len > cap) return FLASHFS_TOO_LARGE;
    if (rd(fs, base + (uint32_t)rel + REC_HDR, buf, len) != FLASHFS_OK) return FLASHFS_IO;
    if (rd16(h + 6) != record_crc(key, len, buf)) return FLASHFS_CORRUPT;
    *out_len = len;
    return FLASHFS_OK;
}

enum flashfs_status flashfs_delete(struct flashfs *fs, uint8_t key)
{
    uint32_t ss, rel;
    int found = 0;
    if (!fs || !fs->mounted) return FLASHFS_INVALID;
    ss = fs->dev.sector_size;
    for (rel = SEC_HDR; rel < fs->cursor; ) {
        uint8_t h[REC_HDR];
        uint16_t rlen;
        if (rd(fs, fs->active * ss + rel, h, REC_HDR) != FLASHFS_OK) break;
        if (rd16(h) != REC_MAGIC) break;
        rlen = rd16(h + 4);
        if (rlen > FLASHFS_MAX_VALUE) break;
        if (h[2] == key && h[3] == ST_LIVE) { kill_record(fs, fs->active, rel); found = 1; }
        rel += REC_HDR + rlen;
    }
    return found ? FLASHFS_OK : FLASHFS_NOT_FOUND;
}

const char *flashfs_status_name(enum flashfs_status status)
{
    static const char *const names[] = {
        "ok", "not-found", "no-space", "too-large", "corrupt", "io", "invalid"
    };
    return (unsigned)status < sizeof(names) / sizeof(names[0]) ? names[status] : "unknown";
}
