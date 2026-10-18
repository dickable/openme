/*
 * OpenME deterministic ME-platform scaffold.
 *
 * This models the observable platform pieces needed by a future CSME runtime
 * experiment. It is not Intel firmware, does not implement authentication,
 * and never writes to the supplied SPI image.
 */
#ifndef OPENME_ME_PLATFORM_H
#define OPENME_ME_PLATFORM_H

#include <stddef.h>
#include <stdint.h>

#define OPENME_ME_ROM_BASE       0x00000000u
#define OPENME_ME_ROM_SIZE       0x00010000u
#define OPENME_ME_SRAM_BASE      0x00100000u
#define OPENME_ME_SRAM_SIZE      0x00080000u
#define OPENME_ME_DRAM_BASE      0x00200000u
#define OPENME_ME_DRAM_SIZE      0x00200000u
#define OPENME_ME_SPI_BASE       0x10000000u
#define OPENME_ME_PCH_BASE       0x20000000u
#define OPENME_ME_PCH_SIZE       0x00010000u
#define OPENME_ME_MEI_BASE       0x20010000u
#define OPENME_ME_MEI_SIZE       0x00001000u

enum openme_me_boot_state {
    OPENME_ME_RESET = 0,
    OPENME_ME_ROM,
    OPENME_ME_PLATFORM_INIT,
    OPENME_ME_SPI_READY,
    OPENME_ME_MEI_READY,
    OPENME_ME_AUTH_PENDING,
    OPENME_ME_REJECTED,
    OPENME_ME_RUNNING,
    OPENME_ME_FAULT,
};

enum openme_me_pch_register {
    OPENME_ME_PCH_CLOCK_CONTROL = 0x00,
    OPENME_ME_PCH_POWER_CONTROL = 0x04,
    OPENME_ME_PCH_RESET_CONTROL = 0x08,
    OPENME_ME_PCH_STATUS = 0x0c,
    OPENME_ME_SPI_COMMAND = 0x100,
    OPENME_ME_SPI_ADDRESS = 0x104,
    OPENME_ME_SPI_DATA = 0x108,
    OPENME_ME_SPI_STATUS = 0x10c,
};

enum openme_me_status_bits {
    OPENME_ME_CLOCK_ON = 1u << 0,
    OPENME_ME_POWER_ON = 1u << 1,
    OPENME_ME_RESET_DEASSERTED = 1u << 2,
    OPENME_ME_SPI_ONLINE = 1u << 3,
    OPENME_ME_MEI_ONLINE = 1u << 4,
    OPENME_ME_AUTH_REQUIRED = 1u << 5,
};

typedef struct openme_me_platform {
    uint8_t rom[OPENME_ME_ROM_SIZE];
    uint8_t sram[OPENME_ME_SRAM_SIZE];
    uint8_t dram[OPENME_ME_DRAM_SIZE];

    const uint8_t *spi_image;
    size_t spi_size;
    uint32_t spi_command;
    uint32_t spi_address;

    uint32_t clock_control;
    uint32_t power_control;
    uint32_t reset_control;
    uint32_t event_count;
    uint32_t step_count;
    enum openme_me_boot_state state;
    char rejection_reason[160];
} OpenMEPlatform;

void openme_me_platform_init(OpenMEPlatform *platform,
                             const uint8_t *spi_image, size_t spi_size);
void openme_me_platform_reset(OpenMEPlatform *platform);
void openme_me_platform_step(OpenMEPlatform *platform);

int openme_me_platform_read(const OpenMEPlatform *platform,
                            uint32_t address, void *buffer, size_t size);
int openme_me_platform_write(OpenMEPlatform *platform,
                             uint32_t address, const void *buffer, size_t size);

const char *openme_me_boot_state_name(enum openme_me_boot_state state);
const char *openme_me_platform_rejection(const OpenMEPlatform *platform);

#endif
