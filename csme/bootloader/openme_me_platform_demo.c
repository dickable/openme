/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "openme_me_platform.h"

#include <stdio.h>
#include <stdlib.h>

static int read_file(const char *path, uint8_t **data, size_t *size)
{
    FILE *file = fopen(path, "rb");
    long length;

    if (!file) {
        return 1;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return 1;
    }
    length = ftell(file);
    if (length <= 0 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return 1;
    }
    *data = malloc((size_t)length);
    if (!*data || fread(*data, 1, (size_t)length, file) != (size_t)length) {
        free(*data);
        *data = NULL;
        fclose(file);
        return 1;
    }
    fclose(file);
    *size = (size_t)length;
    return 0;
}

int main(int argc, char **argv)
{
    uint8_t *image = NULL;
    size_t image_size = 0;
    uint8_t fpt[4] = { 0 };
    OpenMEPlatform *platform;

    if (argc != 2) {
        fprintf(stderr, "usage: %s <read-only-me-region.bin>\n", argv[0]);
        return 2;
    }
    if (read_file(argv[1], &image, &image_size) != 0) {
        fprintf(stderr, "could not read %s\n", argv[1]);
        return 1;
    }

    platform = calloc(1, sizeof(*platform));
    if (!platform) {
        fprintf(stderr, "could not allocate platform memory\n");
        free(image);
        return 1;
    }
    openme_me_platform_init(platform, image, image_size);
    printf("spi-size=%zu\n", image_size);
    printf("map rom=0x%08x+0x%x sram=0x%08x+0x%x dram=0x%08x+0x%x\n",
           OPENME_ME_ROM_BASE, OPENME_ME_ROM_SIZE,
           OPENME_ME_SRAM_BASE, OPENME_ME_SRAM_SIZE,
           OPENME_ME_DRAM_BASE, OPENME_ME_DRAM_SIZE);
    printf("map spi=0x%08x+0x%zx pch=0x%08x+0x%x mei=0x%08x+0x%x\n",
           OPENME_ME_SPI_BASE, image_size,
           OPENME_ME_PCH_BASE, OPENME_ME_PCH_SIZE,
           OPENME_ME_MEI_BASE, OPENME_ME_MEI_SIZE);

    if (openme_me_platform_read(platform, OPENME_ME_SPI_BASE + 0x10,
                                fpt, sizeof(fpt)) == 0) {
        printf("spi[0x10..0x13]=%02x %02x %02x %02x\n",
               fpt[0], fpt[1], fpt[2], fpt[3]);
    }

    printf("state=%s\n", openme_me_boot_state_name(platform->state));
    while (platform->state != OPENME_ME_REJECTED &&
           platform->state != OPENME_ME_FAULT &&
           platform->step_count < 16) {
        openme_me_platform_step(platform);
        printf("step=%u state=%s pch-status=0x%08x\n",
               platform->step_count,
               openme_me_boot_state_name(platform->state),
               platform->clock_control | platform->power_control |
               (!platform->reset_control ? OPENME_ME_RESET_DEASSERTED : 0));
    }
    if (openme_me_platform_rejection(platform)) {
        printf("result=%s\n", openme_me_platform_rejection(platform));
    }

    {
        int success = platform->state == OPENME_ME_REJECTED;
        free(platform);
        free(image);
        return success ? 0 : 1;
    }
}
