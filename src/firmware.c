/* SPDX-License-Identifier: MIT */
#include "firmware.h"

int om_firmware_boot(struct om_firmware *fw, const struct om_hal *hal,
                     struct om_platform_id id, const struct flash_dev *flash,
                     struct om_boot_report *r)
{
    const char *name = "", *reason = "";

    fw->powered = 0; /* failed reboots must not leave the previous service gate open */

    r->support = om_platform_check(id, &name, &reason);
    r->platform_name = name;
    r->support_reason = reason;
    r->hal_bringup = OM_HAL_ERROR;
    r->fs_status = FLASHFS_INVALID;
    r->fs_formatted = 0;
    r->heci_ready = 0;
    r->network = OPENME_CAP_NETWORK; /* always 0: no network by construction */
    r->boot_count = 0;
    r->ok = 0;

    /* 1. Refuse to run on hardware we don't support. */
    if (r->support == OM_SUPPORT_UNSUPPORTED)
        return 0;

    /* 2. Bring the platform up through its HAL. */
    fw->hal = hal;
    r->hal_bringup = hal->bringup();
    if (r->hal_bringup != OM_HAL_OK)
        return 0;

    /* 3. Mount the config filesystem; format it on first boot. */
    r->fs_status = flashfs_mount(&fw->fs, flash);
    if (r->fs_status == FLASHFS_CORRUPT) {
        r->fs_status = flashfs_format(&fw->fs, flash);
        r->fs_formatted = 1;
    }
    if (r->fs_status != FLASHFS_OK)
        return 0;

    /* 3b. Persistent config: a boot counter (key 0) read from and written back
     * to the filesystem, so firmware state survives a reboot on retained flash. */
    {
        uint8_t v[4];
        uint32_t cnt = 0, len = 0;
        enum flashfs_status status = flashfs_get(&fw->fs, 0, v, sizeof(v), &len);
        if (status != FLASHFS_OK && status != FLASHFS_NOT_FOUND) {
            r->fs_status = status;
            return 0;
        }
        if (status == FLASHFS_OK && len != 4) {
            r->fs_status = FLASHFS_CORRUPT;
            return 0;
        }
        if (status == FLASHFS_OK)
            cnt = (uint32_t)v[0] | ((uint32_t)v[1] << 8) |
                  ((uint32_t)v[2] << 16) | ((uint32_t)v[3] << 24);
        if (cnt == UINT32_MAX) {
            r->fs_status = FLASHFS_INVALID;
            return 0;
        }
        ++cnt;
        v[0] = (uint8_t)cnt; v[1] = (uint8_t)(cnt >> 8);
        v[2] = (uint8_t)(cnt >> 16); v[3] = (uint8_t)(cnt >> 24);
        r->fs_status = flashfs_set(&fw->fs, 0, v, 4);
        if (r->fs_status != FLASHFS_OK)
            return 0;
        r->boot_count = cnt;
    }

    /* 4. Reset the HECI transport, register the service, and mark it ready. */
    om_heci_reset(&fw->heci);
    fw->heci.service = &om_service_echo;
    r->heci_ready = 1;

    /* 5. Stay DORMANT. Bring-up is done, but services do not run until the
     * system is powered on (S0) via om_firmware_power(). */
    fw->powered = 0;

    r->ok = 1;
    return 1;
}

int om_firmware_service_once(struct om_firmware *fw)
{
    uint8_t pkt[OM_HECI_PACKET];
    size_t n = 0;
    int work = 0;

    if (!fw || !fw->hal) return 0;
    if (!fw->powered) return 0; /* dormant: service nothing until powered on */

    /* Inbound: pull one packet from the HAL ring into the HECI layer. */
    if (fw->hal->recv(pkt, sizeof(pkt), &n) == OM_HAL_OK) {
        om_heci_receive(&fw->heci, pkt, n);
        work = 1;
    }

    /* Outbound: let the HECI layer emit one packet and push it to the HAL. */
    n = om_heci_transmit(&fw->heci, pkt, sizeof(pkt));
    if (n) {
        fw->hal->send(pkt, n);
        work = 1;
    }

    return work;
}

void om_firmware_service(struct om_firmware *fw, unsigned budget)
{
    while (budget-- && om_firmware_service_once(fw))
        ; /* run until idle or the (bounded) budget is spent */
}

void om_firmware_power(struct om_firmware *fw, int on)
{
    if (fw)
        fw->powered = on ? 1 : 0;
}

void om_firmware_run(struct om_firmware *fw)
{
    for (;;)
        om_firmware_service_once(fw);
}
