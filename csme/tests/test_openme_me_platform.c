/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "../bootloader/openme_me_platform.h"

#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

int main(void)
{
    uint8_t image[0x40] = { 0 };
    uint8_t value[4] = { 0 };
    OpenMEPlatform *platform = calloc(1, sizeof(*platform));

    assert(platform != NULL);

    memcpy(image + 0x10, "$FPT", 4);
    openme_me_platform_init(platform, image, sizeof(image));

    assert(openme_me_platform_read(platform, OPENME_ME_SPI_BASE + 0x10,
                                   value, sizeof(value)) == 0);
    assert(memcmp(value, "$FPT", 4) == 0);
    assert(openme_me_platform_write(platform, OPENME_ME_SPI_BASE,
                                    value, sizeof(value)) == -EPERM);

    for (unsigned int i = 0; i < 6; ++i) {
        openme_me_platform_step(platform);
    }
    assert(platform->state == OPENME_ME_REJECTED);
    assert(strcmp(openme_me_platform_rejection(platform),
                  "firmware authentication/runtime loader not implemented") == 0);
    /* FAULT sorts after RUNNING but must not advertise online peripherals. */
    openme_me_platform_init(platform, NULL, 0);
    for (unsigned int i = 0; i < 3; ++i) {
        openme_me_platform_step(platform);
    }
    assert(platform->state == OPENME_ME_FAULT);
    assert(openme_me_platform_read(platform, OPENME_ME_PCH_BASE + OPENME_ME_PCH_STATUS,
                                   value, sizeof(value)) == 0);
    assert(value[0] == (OPENME_ME_CLOCK_ON | OPENME_ME_POWER_ON | OPENME_ME_RESET_DEASSERTED));
    assert(openme_me_platform_read(platform, OPENME_ME_MEI_BASE, value, sizeof(value)) == 0);
    assert(value[0] == 0);
    free(platform);
    return 0;
}
