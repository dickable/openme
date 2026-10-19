/* SPDX-License-Identifier: MIT */
#ifndef OPENME_HAL_H
#define OPENME_HAL_H

#include <stddef.h>
#include <stdint.h>

/*
 * OpenME hardware abstraction layer.
 *
 * The portable core (src/core.c) and the HECI/HBM protocol layer
 * (src/mei/heci.c) operate only on byte buffers. The HAL is the single seam
 * below them that touches a specific platform: it brings the ME up and moves
 * raw HECI packets to and from that platform's circular-buffer rings.
 *
 * Adding a supported platform (see docs/openme-architecture.md) means writing
 * one new `struct om_hal` implementation. The core is never edited for a port.
 *
 * A HAL implementation touches only hardware that PERMITS owner firmware. It
 * implements no bypass of any verification mechanism; a platform that would
 * require defeating a signature check to run owner code does not get a HAL.
 *
 * NO-NETWORK INVARIANT: the only I/O this interface exposes is a LOCAL host<->ME
 * transport (HECI recv/send), plus bring-up and a tick source. There is no
 * network, NIC, or off-die-comms operation here, and one must never be added.
 * OpenME cannot be remotely controlled because the HAL gives it no way to be
 * (see src/capabilities.h).
 */

enum om_hal_status {
    OM_HAL_OK = 0,
    OM_HAL_NOT_IMPLEMENTED, /* this port has not implemented the operation yet */
    OM_HAL_EMPTY,           /* recv: no packet is currently pending */
    OM_HAL_AGAIN,           /* operation would block; retry later */
    OM_HAL_ERROR
};

struct om_hal {
    const char *name;          /* short id, e.g. "model", "gm45" */
    const char *me_generation; /* e.g. "emulation", "ME 4/5 (GM45/ICH9M-E)" */

    /* Bring the ME/platform to the point where HECI transport is usable.
     * On real silicon this is the undocumented ARC/platform bring-up. */
    enum om_hal_status (*bringup)(void);

    /* Pull one raw HECI packet (4-byte header + payload) from the ring into
     * `buf` (capacity `cap`), setting *out_len. OM_HAL_EMPTY when none pend. */
    enum om_hal_status (*recv)(uint8_t *buf, size_t cap, size_t *out_len);

    /* Push one raw HECI packet to the ring. */
    enum om_hal_status (*send)(const uint8_t *buf, size_t len);

    /* Monotonic tick source for timeouts/watchdog/flow-control timing. Units
     * are platform-defined (a free-running counter); only ordering/difference
     * is meaningful. Must not go backwards. */
    uint32_t (*ticks)(void);
};

/* Provided ports. `model` is the emulation HAL used by the QEMU target;
 * `gm45` is the first real-hardware reference port (currently a stub). */
extern const struct om_hal om_hal_model;
extern const struct om_hal om_hal_gm45;
extern const struct om_hal om_hal_serial; /* COM2 transport for the host-driver test */

const char *om_hal_status_name(enum om_hal_status status);

/* Model HAL test hooks: act as the host on the other side of the ring. These
 * exist only for the emulation backend (om_hal_model). */
void om_model_reset(void);
enum om_hal_status om_model_host_send(const uint8_t *buf, size_t len);
enum om_hal_status om_model_host_recv(uint8_t *buf, size_t cap, size_t *out_len);

#endif
