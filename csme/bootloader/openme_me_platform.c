/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "openme_me_platform.h"

#include <errno.h>
#include <string.h>

static int range_contains(uint32_t base, size_t region_size,
                          uint32_t address, size_t size)
{
    uint64_t end = (uint64_t)address + size;
    uint64_t region_end = (uint64_t)base + region_size;

    return address >= base && end <= region_end;
}

static uint32_t load_le32(const uint8_t *data)
{
    return (uint32_t)data[0] |
           ((uint32_t)data[1] << 8) |
           ((uint32_t)data[2] << 16) |
           ((uint32_t)data[3] << 24);
}

static void store_le32(uint8_t *data, uint32_t value)
{
    data[0] = (uint8_t)value;
    data[1] = (uint8_t)(value >> 8);
    data[2] = (uint8_t)(value >> 16);
    data[3] = (uint8_t)(value >> 24);
}

static int valid_scalar_size(size_t size)
{
    return size == 1 || size == 2 || size == 4;
}

static void scalar_store(uint8_t *data, uint32_t value, size_t size)
{
    if (size == 1) {
        data[0] = (uint8_t)value;
    } else if (size == 2) {
        data[0] = (uint8_t)value;
        data[1] = (uint8_t)(value >> 8);
    } else {
        store_le32(data, value);
    }
}

const char *openme_me_boot_state_name(enum openme_me_boot_state state)
{
    switch (state) {
    case OPENME_ME_RESET:
        return "reset";
    case OPENME_ME_ROM:
        return "rom";
    case OPENME_ME_PLATFORM_INIT:
        return "platform-init";
    case OPENME_ME_SPI_READY:
        return "spi-ready";
    case OPENME_ME_MEI_READY:
        return "mei-ready";
    case OPENME_ME_AUTH_PENDING:
        return "auth-pending";
    case OPENME_ME_REJECTED:
        return "rejected";
    case OPENME_ME_RUNNING:
        return "running";
    case OPENME_ME_FAULT:
        return "fault";
    default:
        return "unknown";
    }
}

static void set_rejection(OpenMEPlatform *platform, const char *reason)
{
    size_t length = strlen(reason);

    if (length >= sizeof(platform->rejection_reason)) {
        length = sizeof(platform->rejection_reason) - 1;
    }
    memcpy(platform->rejection_reason, reason, length);
    platform->rejection_reason[length] = '\0';
}

void openme_me_platform_reset(OpenMEPlatform *platform)
{
    memset(platform->rom, 0, sizeof(platform->rom));
    memset(platform->sram, 0, sizeof(platform->sram));
    memset(platform->dram, 0, sizeof(platform->dram));
    platform->spi_command = 0;
    platform->spi_address = 0;
    platform->clock_control = 0;
    platform->power_control = 0;
    platform->reset_control = 1;
    platform->event_count = 0;
    platform->step_count = 0;
    platform->state = OPENME_ME_RESET;
    platform->rejection_reason[0] = '\0';
}

void openme_me_platform_init(OpenMEPlatform *platform,
                             const uint8_t *spi_image, size_t spi_size)
{
    memset(platform, 0, sizeof(*platform));
    platform->spi_image = spi_image;
    platform->spi_size = spi_size;
    openme_me_platform_reset(platform);
}

void openme_me_platform_step(OpenMEPlatform *platform)
{
    platform->step_count++;

    switch (platform->state) {
    case OPENME_ME_RESET:
        platform->clock_control = OPENME_ME_CLOCK_ON;
        platform->power_control = OPENME_ME_POWER_ON;
        platform->state = OPENME_ME_ROM;
        break;
    case OPENME_ME_ROM:
        if (!(platform->clock_control & OPENME_ME_CLOCK_ON) ||
            !(platform->power_control & OPENME_ME_POWER_ON)) {
            platform->state = OPENME_ME_FAULT;
            set_rejection(platform, "clock or power did not become ready");
            break;
        }
        platform->reset_control = 0;
        platform->state = OPENME_ME_PLATFORM_INIT;
        break;
    case OPENME_ME_PLATFORM_INIT:
        if (!platform->spi_image || platform->spi_size == 0) {
            platform->state = OPENME_ME_FAULT;
            set_rejection(platform, "no SPI image is attached");
            break;
        }
        platform->state = OPENME_ME_SPI_READY;
        break;
    case OPENME_ME_SPI_READY:
        platform->state = OPENME_ME_MEI_READY;
        break;
    case OPENME_ME_MEI_READY:
        platform->state = OPENME_ME_AUTH_PENDING;
        break;
    case OPENME_ME_AUTH_PENDING:
        /*
         * This is intentionally a hard boundary. The scaffold does not
         * implement or bypass Intel authentication. A future loader may
         * observe a vendor-provided result here, but this model never turns
         * an unknown image into RUNNING by assumption.
         */
        platform->state = OPENME_ME_REJECTED;
        set_rejection(platform,
                      "firmware authentication/runtime loader not implemented");
        break;
    case OPENME_ME_REJECTED:
    case OPENME_ME_RUNNING:
    case OPENME_ME_FAULT:
        break;
    default:
        platform->state = OPENME_ME_FAULT;
        set_rejection(platform, "invalid boot state");
        break;
    }
    platform->event_count++;
}

static int read_pch(const OpenMEPlatform *platform, uint32_t offset,
                    void *buffer, size_t size)
{
    uint32_t value;

    if (!valid_scalar_size(size) || size != 4 || (offset & 3)) {
        return -EINVAL;
    }
    switch (offset) {
    case OPENME_ME_PCH_CLOCK_CONTROL:
        value = platform->clock_control;
        break;
    case OPENME_ME_PCH_POWER_CONTROL:
        value = platform->power_control;
        break;
    case OPENME_ME_PCH_RESET_CONTROL:
        value = platform->reset_control;
        break;
    case OPENME_ME_PCH_STATUS:
        value = (platform->clock_control ? OPENME_ME_CLOCK_ON : 0) |
                (platform->power_control ? OPENME_ME_POWER_ON : 0) |
                (!platform->reset_control ? OPENME_ME_RESET_DEASSERTED : 0) |
                (platform->state >= OPENME_ME_SPI_READY &&
                 platform->state <= OPENME_ME_RUNNING ? OPENME_ME_SPI_ONLINE : 0) |
                (platform->state >= OPENME_ME_MEI_READY &&
                 platform->state <= OPENME_ME_RUNNING ? OPENME_ME_MEI_ONLINE : 0) |
                (platform->state == OPENME_ME_AUTH_PENDING ? OPENME_ME_AUTH_REQUIRED : 0);
        break;
    case OPENME_ME_SPI_COMMAND:
        value = platform->spi_command;
        break;
    case OPENME_ME_SPI_ADDRESS:
        value = platform->spi_address;
        break;
    case OPENME_ME_SPI_STATUS:
        value = platform->spi_image ? 1u : 0u;
        break;
    default:
        return -ENOENT;
    }
    store_le32(buffer, value);
    return 0;
}

static int write_pch(OpenMEPlatform *platform, uint32_t offset,
                     const void *buffer, size_t size)
{
    uint32_t value;

    if (!valid_scalar_size(size) || size != 4 || (offset & 3)) {
        return -EINVAL;
    }
    value = load_le32(buffer);
    switch (offset) {
    case OPENME_ME_PCH_CLOCK_CONTROL:
        platform->clock_control = value & OPENME_ME_CLOCK_ON;
        return 0;
    case OPENME_ME_PCH_POWER_CONTROL:
        platform->power_control = value & OPENME_ME_POWER_ON;
        return 0;
    case OPENME_ME_PCH_RESET_CONTROL:
        platform->reset_control = value & 1u;
        return 0;
    case OPENME_ME_SPI_COMMAND:
        platform->spi_command = value & 0xffu;
        return 0;
    case OPENME_ME_SPI_ADDRESS:
        platform->spi_address = value;
        return 0;
    case OPENME_ME_SPI_DATA:
        return -EPERM;
    default:
        return -ENOENT;
    }
}

int openme_me_platform_read(const OpenMEPlatform *platform,
                            uint32_t address, void *buffer, size_t size)
{
    uint32_t value;

    if (!buffer || !valid_scalar_size(size)) {
        return -EINVAL;
    }
    if (range_contains(OPENME_ME_ROM_BASE, sizeof(platform->rom), address, size)) {
        memcpy(buffer, platform->rom + address - OPENME_ME_ROM_BASE, size);
        return 0;
    }
    if (range_contains(OPENME_ME_SRAM_BASE, sizeof(platform->sram), address, size)) {
        memcpy(buffer, platform->sram + address - OPENME_ME_SRAM_BASE, size);
        return 0;
    }
    if (range_contains(OPENME_ME_DRAM_BASE, sizeof(platform->dram), address, size)) {
        memcpy(buffer, platform->dram + address - OPENME_ME_DRAM_BASE, size);
        return 0;
    }
    if (address >= OPENME_ME_SPI_BASE &&
        (uint64_t)address + size <= (uint64_t)OPENME_ME_SPI_BASE + platform->spi_size) {
        if (!platform->spi_image) {
            return -ENODEV;
        }
        memcpy(buffer, platform->spi_image + address - OPENME_ME_SPI_BASE, size);
        return 0;
    }
    if (range_contains(OPENME_ME_PCH_BASE, OPENME_ME_PCH_SIZE, address, size)) {
        return read_pch(platform, address - OPENME_ME_PCH_BASE, buffer, size);
    }
    if (range_contains(OPENME_ME_MEI_BASE, OPENME_ME_MEI_SIZE, address, size)) {
        value = platform->state >= OPENME_ME_MEI_READY &&
                platform->state <= OPENME_ME_RUNNING ? 1u : 0u;
        scalar_store(buffer, value, size);
        return 0;
    }
    return -EFAULT;
}

int openme_me_platform_write(OpenMEPlatform *platform,
                             uint32_t address, const void *buffer, size_t size)
{
    if (!buffer || !valid_scalar_size(size)) {
        return -EINVAL;
    }
    if (range_contains(OPENME_ME_ROM_BASE, sizeof(platform->rom), address, size)) {
        return -EPERM;
    }
    if (range_contains(OPENME_ME_SRAM_BASE, sizeof(platform->sram), address, size)) {
        memcpy(platform->sram + address - OPENME_ME_SRAM_BASE, buffer, size);
        return 0;
    }
    if (range_contains(OPENME_ME_DRAM_BASE, sizeof(platform->dram), address, size)) {
        memcpy(platform->dram + address - OPENME_ME_DRAM_BASE, buffer, size);
        return 0;
    }
    if (address >= OPENME_ME_SPI_BASE &&
        (uint64_t)address + size <= (uint64_t)OPENME_ME_SPI_BASE + platform->spi_size) {
        return -EPERM;
    }
    if (range_contains(OPENME_ME_PCH_BASE, OPENME_ME_PCH_SIZE, address, size)) {
        return write_pch(platform, address - OPENME_ME_PCH_BASE, buffer, size);
    }
    if (range_contains(OPENME_ME_MEI_BASE, OPENME_ME_MEI_SIZE, address, size)) {
        return -ENOSYS;
    }
    return -EFAULT;
}

const char *openme_me_platform_rejection(const OpenMEPlatform *platform)
{
    return platform->rejection_reason[0] ? platform->rejection_reason : NULL;
}
