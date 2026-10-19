/* SPDX-License-Identifier: MIT */
#ifndef OPENME_CAPABILITIES_H
#define OPENME_CAPABILITIES_H

/*
 * OpenME capability manifest — the project's core trust properties.
 *
 * NETWORK IS DELIBERATELY AND PERMANENTLY ABSENT.
 *
 * The stock Intel ME's defining danger is that it is an always-on coprocessor
 * with its own network path (AMT), invisible to the OS — i.e. a built-in remote
 * control. OpenME removes that capability by construction: it has no network
 * stack, no AMT, no out-of-band remote management, and no off-die comms. It
 * therefore cannot be controlled or surveilled remotely, because it has no
 * mechanism to be — a guarantee you can verify by reading the source, not a
 * promise.
 *
 * This is enforced structurally, not just declared here:
 *   - the HAL (src/hal/hal.h) exposes ONLY a local host<->ME transport
 *     (HECI recv/send), bring-up, and a tick source. It has NO network / NIC /
 *     off-die operation, and must never gain one.
 *   - no service (src/service/) performs or requests network I/O.
 *
 * These flags are 0 permanently. Changing either to 1 is out of scope for this
 * project and would violate its entire reason to exist.
 */
#define OPENME_CAP_NETWORK        0 /* no network stack, ever */
#define OPENME_CAP_REMOTE_CONTROL 0 /* no AMT / out-of-band management, ever */

#endif
