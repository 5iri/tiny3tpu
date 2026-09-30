#ifndef TINY3TPU_AXIS_MAILBOX_H
#define TINY3TPU_AXIS_MAILBOX_H

#include <stdint.h>

#include "tiny3tpu_mmio_backend.h"

#ifdef __cplusplus
extern "C" {
#endif

enum {
    TINY3TPU_AXIS_MAILBOX_HEADER = 0x00,
    TINY3TPU_AXIS_MAILBOX_DATA = 0x04,
    TINY3TPU_AXIS_MAILBOX_CONTROL = 0x08,
    TINY3TPU_AXIS_MAILBOX_STATUS = 0x0c,
    TINY3TPU_AXIS_MAILBOX_RESP_CODE = 0x10,
    TINY3TPU_AXIS_MAILBOX_RESP_DATA = 0x14
};

enum {
    TINY3TPU_AXIS_MAILBOX_SUBMIT = 1u << 0,
    TINY3TPU_AXIS_MAILBOX_ACK = 1u << 1,
    TINY3TPU_AXIS_MAILBOX_CLEAR_MISUSE = 1u << 2,
    TINY3TPU_AXIS_MAILBOX_STATUS_BUSY = 1u << 0,
    TINY3TPU_AXIS_MAILBOX_STATUS_READY = 1u << 1,
    TINY3TPU_AXIS_MAILBOX_STATUS_MISUSE = 1u << 2
};

enum {
    TINY3TPU_AXIS_MAILBOX_RESP_OKAY = 0,
    TINY3TPU_AXIS_MAILBOX_RESP_SLVERR = 2,
    TINY3TPU_AXIS_MAILBOX_RESP_DECERR = 3
};

/* The callback layout intentionally matches tiny3tpu_mmio.  Offsets passed
 * to callbacks are mailbox-local byte offsets; no accelerator base address
 * is embedded in this driver. */
typedef struct tiny3tpu_axis_mailbox {
    void *user;
    int (*read32)(void *user, uint32_t offset, uint32_t *value);
    int (*write32)(void *user, uint32_t offset, uint32_t value);
    uint32_t poll_limit;
    int poisoned;
} tiny3tpu_axis_mailbox;

/* Initialize from callbacks with the same signatures as tiny3tpu_mmio. */
int tiny3tpu_axis_mailbox_init(
    tiny3tpu_axis_mailbox *mailbox, void *user,
    int (*read32)(void *user, uint32_t offset, uint32_t *value),
    int (*write32)(void *user, uint32_t offset, uint32_t value),
    uint32_t poll_limit);

/* Convenience adapter for the existing tiny3tpu_mmio callback object. */
int tiny3tpu_axis_mailbox_init_from_mmio(
    tiny3tpu_axis_mailbox *mailbox, const tiny3tpu_mmio *lowlevel);

/* Clear the software fail-closed latch only after hardware reset/drain. */
void tiny3tpu_axis_mailbox_reset(tiny3tpu_axis_mailbox *mailbox);
int tiny3tpu_axis_mailbox_is_poisoned(
    const tiny3tpu_axis_mailbox *mailbox);

/* Target offset is the byte offset encoded in the outgoing AXIS header. */
int tiny3tpu_axis_mailbox_read(tiny3tpu_axis_mailbox *mailbox,
                               uint32_t target_offset, uint32_t *value);
int tiny3tpu_axis_mailbox_write(tiny3tpu_axis_mailbox *mailbox,
                                uint32_t target_offset, uint32_t value,
                                uint8_t wstrb);

/* Full-word convenience wrappers. */
int tiny3tpu_axis_mailbox_read32(void *user, uint32_t target_offset,
                                 uint32_t *value);
int tiny3tpu_axis_mailbox_write32(void *user, uint32_t target_offset,
                                  uint32_t value);

#ifdef __cplusplus
}
#endif

#endif
