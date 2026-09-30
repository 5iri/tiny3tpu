#include "tiny3tpu_axis_mailbox.h"

#include <stddef.h>

static void poison(tiny3tpu_axis_mailbox *mailbox)
{
    if (mailbox != NULL) mailbox->poisoned = 1;
}

static int write_local(tiny3tpu_axis_mailbox *mailbox, uint32_t offset,
                       uint32_t value)
{
    if (mailbox->write32(mailbox->user, offset, value)) {
        poison(mailbox);
        return -1;
    }
    return 0;
}

static int read_local(tiny3tpu_axis_mailbox *mailbox, uint32_t offset,
                      uint32_t *value)
{
    if (mailbox->read32(mailbox->user, offset, value)) {
        poison(mailbox);
        return -1;
    }
    return 0;
}

static int submit_and_wait(tiny3tpu_axis_mailbox *mailbox,
                           uint32_t target_offset, uint32_t payload,
                           uint8_t wstrb, int is_write, uint32_t *value)
{
    uint32_t status, code, response_data = 0;
    uint32_t poll;

    if (mailbox == NULL || mailbox->read32 == NULL ||
        mailbox->write32 == NULL || mailbox->poll_limit == 0U ||
        mailbox->poisoned || target_offset > UINT32_C(0xff) ||
        (!is_write && value == NULL))
        return -1;

    /* A pre-existing transaction/result makes ownership ambiguous.  Do not
     * submit over it and do not permit a later call to consume its result. */
    if (read_local(mailbox, TINY3TPU_AXIS_MAILBOX_STATUS, &status) ||
        (status & TINY3TPU_AXIS_MAILBOX_STATUS_MISUSE) ||
        (status & (TINY3TPU_AXIS_MAILBOX_STATUS_BUSY |
                   TINY3TPU_AXIS_MAILBOX_STATUS_READY))) {
        poison(mailbox);
        return -1;
    }

    payload = is_write ? payload : 0U;
    if (write_local(mailbox, TINY3TPU_AXIS_MAILBOX_HEADER,
                    (target_offset & UINT32_C(0xff)) |
                    (is_write ? UINT32_C(1) << 8 : 0U) |
                    ((uint32_t)(wstrb & 0x0fU) << 12)) ||
        write_local(mailbox, TINY3TPU_AXIS_MAILBOX_DATA, payload) ||
        write_local(mailbox, TINY3TPU_AXIS_MAILBOX_CONTROL,
                    TINY3TPU_AXIS_MAILBOX_SUBMIT))
        return -1;

    for (poll = 0; poll < mailbox->poll_limit; ++poll) {
        if (read_local(mailbox, TINY3TPU_AXIS_MAILBOX_STATUS, &status))
            return -1;
        if (status & TINY3TPU_AXIS_MAILBOX_STATUS_MISUSE) {
            poison(mailbox);
            return -1;
        }
        if (status & TINY3TPU_AXIS_MAILBOX_STATUS_READY)
            break;
    }
    if (poll == mailbox->poll_limit) {
        /* The command may still complete after this function returns.  A
         * later call is therefore forbidden until the device is reset. */
        poison(mailbox);
        return -1;
    }

    if (read_local(mailbox, TINY3TPU_AXIS_MAILBOX_RESP_CODE, &code) ||
        read_local(mailbox, TINY3TPU_AXIS_MAILBOX_RESP_DATA, &response_data) ||
        write_local(mailbox, TINY3TPU_AXIS_MAILBOX_CONTROL,
                    TINY3TPU_AXIS_MAILBOX_ACK))
        return -1;

    if (code != TINY3TPU_AXIS_MAILBOX_RESP_OKAY)
        return -1;
    if (!is_write)
        *value = response_data;
    return 0;
}

int tiny3tpu_axis_mailbox_init(
    tiny3tpu_axis_mailbox *mailbox, void *user,
    int (*read32)(void *user, uint32_t offset, uint32_t *value),
    int (*write32)(void *user, uint32_t offset, uint32_t value),
    uint32_t poll_limit)
{
    if (mailbox == NULL) return -1;
    mailbox->user = user;
    mailbox->read32 = read32;
    mailbox->write32 = write32;
    mailbox->poll_limit = poll_limit;
    mailbox->poisoned = (read32 == NULL || write32 == NULL ||
                         poll_limit == 0U);
    return mailbox->poisoned ? -1 : 0;
}

int tiny3tpu_axis_mailbox_init_from_mmio(
    tiny3tpu_axis_mailbox *mailbox, const tiny3tpu_mmio *lowlevel)
{
    if (lowlevel == NULL)
        return tiny3tpu_axis_mailbox_init(mailbox, NULL, NULL, NULL, 0U);
    return tiny3tpu_axis_mailbox_init(
        mailbox, lowlevel->user, lowlevel->read32, lowlevel->write32,
        lowlevel->poll_limit);
}

void tiny3tpu_axis_mailbox_reset(tiny3tpu_axis_mailbox *mailbox)
{
    if (mailbox != NULL && mailbox->read32 != NULL &&
        mailbox->write32 != NULL && mailbox->poll_limit != 0U)
        mailbox->poisoned = 0;
}

int tiny3tpu_axis_mailbox_is_poisoned(
    const tiny3tpu_axis_mailbox *mailbox)
{
    return mailbox == NULL ? 1 : mailbox->poisoned != 0;
}

int tiny3tpu_axis_mailbox_read(tiny3tpu_axis_mailbox *mailbox,
                               uint32_t target_offset, uint32_t *value)
{
    if (value == NULL) return -1;
    return submit_and_wait(mailbox, target_offset, 0U, 0U, 0, value);
}

int tiny3tpu_axis_mailbox_write(tiny3tpu_axis_mailbox *mailbox,
                                uint32_t target_offset, uint32_t value,
                                uint8_t wstrb)
{
    return submit_and_wait(mailbox, target_offset, value, wstrb, 1, NULL);
}

int tiny3tpu_axis_mailbox_read32(void *user, uint32_t target_offset,
                                 uint32_t *value)
{
    return tiny3tpu_axis_mailbox_read((tiny3tpu_axis_mailbox *)user,
                                      target_offset, value);
}

int tiny3tpu_axis_mailbox_write32(void *user, uint32_t target_offset,
                                  uint32_t value)
{
    return tiny3tpu_axis_mailbox_write((tiny3tpu_axis_mailbox *)user,
                                       target_offset, value, 0x0fU);
}
