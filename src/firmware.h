/* SPDX-License-Identifier: MIT */
#ifndef OPENME_FIRMWARE_H
#define OPENME_FIRMWARE_H

#include "hal/hal.h"
#include "fs/flashfs.h"
#include "mei/heci.h"
#include "platform/support.h"
#include "service/service.h"
#include "capabilities.h"

/*
 * Top-level OpenME firmware bring-up.
 *
 * This is the platform-independent "boot" of the ME firmware: it ties the
 * subsystems together in order and is what a real platform entry point would
 * call. It touches no chipset registers directly — all hardware access is
 * through the supplied HAL and flash backend — so it runs identically in
 * emulation and (eventually) on a real port.
 */

struct om_firmware {
    const struct om_hal *hal;
    struct flashfs fs;
    struct om_heci heci;
    /* Dormant-by-default power gate. Unlike the stock ME (active in standby/off),
     * OpenME services nothing until the system is actually powered on (S0). A
     * real port drives this from the detected host power state / power-button
     * event; in emulation it is set via om_firmware_power(). */
    int powered;
};

struct om_boot_report {
    enum om_support support;
    const char *platform_name;
    const char *support_reason;
    enum om_hal_status hal_bringup;
    enum flashfs_status fs_status;
    int fs_formatted; /* 1 if first-boot format, 0 if an existing store mounted */
    int heci_ready;
    int network;      /* declared network capability; always 0 (see capabilities.h) */
    uint32_t boot_count; /* persistent boot counter read from / written to flash */
    int ok;
};

/*
 * Staged bring-up: platform guard -> HAL bring-up -> config filesystem -> HECI.
 * Returns 1 on a fully-ready firmware, 0 otherwise, and fills `report` with the
 * per-stage outcome. Refuses (returns 0) on unsupported hardware or any failed
 * stage, so a bad platform stops here instead of proceeding blindly.
 */
int om_firmware_boot(struct om_firmware *fw, const struct om_hal *hal,
                     struct om_platform_id id, const struct flash_dev *flash,
                     struct om_boot_report *report);

/*
 * One service iteration: move one inbound packet HAL->HECI and drain one
 * outbound packet HECI->HAL. Returns 1 if it did any work, 0 if idle. The
 * protocol now rides the HAL seam rather than being hand-fed.
 */
int om_firmware_service_once(struct om_firmware *fw);

/*
 * Pump the service loop until it goes idle or `budget` iterations elapse
 * (bounded so callers/tests always terminate). A real platform entry point
 * calls om_firmware_service_once() forever instead.
 */
void om_firmware_service(struct om_firmware *fw, unsigned budget);

/*
 * Set the power gate. `on` != 0 means the system is powered on (S0): services
 * run. 0 means dormant (standby/off): the service loop does nothing. The
 * firmware boots dormant; this models the power button / S0 transition.
 */
void om_firmware_power(struct om_firmware *fw, int on);

/*
 * Production autonomous entry: service the HAL forever. The QEMU *test* build
 * runs the interactive shell instead; this is the loop a real platform entry
 * point jumps to, and it is exercised once an external host channel feeds the
 * HAL (see the host-driver work). Never returns.
 */
void om_firmware_run(struct om_firmware *fw);

#endif
