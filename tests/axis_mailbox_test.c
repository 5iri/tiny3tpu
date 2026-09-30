#include "tiny3tpu_axis_mailbox.h"

#include <stdio.h>
#include <string.h>

typedef struct fake_mailbox {
    uint32_t header;
    uint32_t data;
    uint32_t code;
    uint32_t response;
    uint32_t status;
    unsigned polls_to_ready;
    unsigned reads;
    unsigned writes;
    unsigned fail_read_at;
    unsigned fail_write_at;
    int misuse_on_poll;
    int timeout;
} fake_mailbox;

static int read32(void *user, uint32_t offset, uint32_t *value)
{
    fake_mailbox *fake = user;
    ++fake->reads;
    if (fake->fail_read_at != 0U && fake->reads == fake->fail_read_at)
        return -1;
    if (offset == TINY3TPU_AXIS_MAILBOX_STATUS) {
        if (fake->misuse_on_poll &&
            (fake->status & TINY3TPU_AXIS_MAILBOX_STATUS_BUSY))
            fake->status |= TINY3TPU_AXIS_MAILBOX_STATUS_MISUSE;
        if ((fake->status & TINY3TPU_AXIS_MAILBOX_STATUS_BUSY) &&
            !fake->timeout && fake->polls_to_ready != 0U &&
            --fake->polls_to_ready == 0U) {
            fake->status = TINY3TPU_AXIS_MAILBOX_STATUS_READY;
        }
        *value = fake->status;
    } else if (offset == TINY3TPU_AXIS_MAILBOX_RESP_CODE) {
        *value = fake->code;
    } else if (offset == TINY3TPU_AXIS_MAILBOX_RESP_DATA) {
        *value = fake->response;
    } else {
        return -1;
    }
    return 0;
}

static int write32(void *user, uint32_t offset, uint32_t value)
{
    fake_mailbox *fake = user;
    ++fake->writes;
    if (fake->fail_write_at != 0U && fake->writes == fake->fail_write_at)
        return -1;
    if (offset == TINY3TPU_AXIS_MAILBOX_HEADER) {
        fake->header = value;
    } else if (offset == TINY3TPU_AXIS_MAILBOX_DATA) {
        fake->data = value;
    } else if (offset == TINY3TPU_AXIS_MAILBOX_CONTROL &&
               (value & TINY3TPU_AXIS_MAILBOX_SUBMIT) != 0U) {
        fake->status = TINY3TPU_AXIS_MAILBOX_STATUS_BUSY;
        fake->polls_to_ready = 2U;
    } else if (offset == TINY3TPU_AXIS_MAILBOX_CONTROL &&
               (value & TINY3TPU_AXIS_MAILBOX_ACK) != 0U) {
        fake->status &= ~TINY3TPU_AXIS_MAILBOX_STATUS_READY;
    } else {
        return -1;
    }
    return 0;
}

static int expect(int condition, const char *message)
{
    if (!condition) fprintf(stderr, "axis mailbox test: %s\n", message);
    return condition ? 0 : 1;
}

int main(void)
{
    fake_mailbox fake;
    tiny3tpu_axis_mailbox mailbox;
    uint32_t value = 0;
    unsigned before;
    int failures = 0;

    memset(&fake, 0, sizeof(fake));
    fake.code = TINY3TPU_AXIS_MAILBOX_RESP_OKAY;
    fake.response = UINT32_C(0x12345678);
    failures += expect(tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32,
                                                  write32, 5U) == 0,
                       "init accepts callback-compatible arguments");
    failures += expect(tiny3tpu_axis_mailbox_read32(&mailbox, 0x24, &value) == 0,
                       "read transaction succeeds");
    failures += expect(value == UINT32_C(0x12345678), "read data is returned");
    failures += expect(fake.header == UINT32_C(0x24), "read header has no write bit");
    failures += expect(fake.data == 0U, "read payload is zero");
    failures += expect(!tiny3tpu_axis_mailbox_is_poisoned(&mailbox),
                       "successful transaction does not poison context");

    failures += expect(tiny3tpu_axis_mailbox_write(&mailbox, 0x08,
                                                   UINT32_C(0xaabbccdd), 0x5) == 0,
                       "partial AXIL write transaction succeeds");
    failures += expect(fake.header == UINT32_C(0x5108),
                       "write header preserves arbitrary AXIL strobes");
    failures += expect(fake.data == UINT32_C(0xaabbccdd),
                       "write payload is forwarded");

    memset(&fake, 0, sizeof(fake));
    failures += expect(tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32,
                                                  write32, 2U) == 0,
                       "second context init succeeds");
    fake.timeout = 1;
    failures += expect(tiny3tpu_axis_mailbox_read(&mailbox, 0, &value) != 0,
                       "timeout returns bus failure");
    failures += expect(tiny3tpu_axis_mailbox_is_poisoned(&mailbox),
                       "timeout fail-closes the context");
    before = fake.writes + fake.reads;
    fake.timeout = 0;
    failures += expect(tiny3tpu_axis_mailbox_read(&mailbox, 0, &value) != 0,
                       "stale response cannot be reused after timeout");
    failures += expect(before == fake.writes + fake.reads,
                       "poisoned call performs no bus accesses");

    fake.status = 0U; /* Represents an externally applied hardware reset. */
    tiny3tpu_axis_mailbox_reset(&mailbox);
    failures += expect(tiny3tpu_axis_mailbox_read(&mailbox, 0, &value) == 0,
                       "explicit reset reopens the context");

    memset(&fake, 0, sizeof(fake));
    fake.status = TINY3TPU_AXIS_MAILBOX_STATUS_MISUSE;
    failures += expect(tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32,
                                                  write32, 4U) == 0,
                       "sticky misuse context init succeeds");
    before = fake.writes + fake.reads;
    failures += expect(tiny3tpu_axis_mailbox_read32(&mailbox, 0, &value) != 0,
                       "pre-existing misuse is rejected");
    failures += expect(tiny3tpu_axis_mailbox_is_poisoned(&mailbox),
                       "pre-existing misuse fail-closes the context");
    failures += expect(before < fake.writes + fake.reads,
                       "pre-existing misuse was observed");

    memset(&fake, 0, sizeof(fake));
    fake.misuse_on_poll = 1;
    failures += expect(tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32,
                                                  write32, 4U) == 0,
                       "poll misuse context init succeeds");
    failures += expect(tiny3tpu_axis_mailbox_read32(&mailbox, 0, &value) != 0,
                       "new misuse during polling is rejected");
    failures += expect(tiny3tpu_axis_mailbox_is_poisoned(&mailbox),
                       "new misuse during polling fail-closes the context");

    memset(&fake, 0, sizeof(fake));
    failures += expect(tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32,
                                                  write32, 4U) == 0,
                       "error context init succeeds");
    fake.fail_write_at = 2U;
    failures += expect(tiny3tpu_axis_mailbox_write32(&mailbox, 4, 1) != 0,
                       "callback write error propagates");
    failures += expect(tiny3tpu_axis_mailbox_is_poisoned(&mailbox),
                       "callback error fail-closes the context");

    /* Every callback failure point must fail closed, including result ACK. */
    for (unsigned operation = 0; operation < 2; ++operation) {
        for (unsigned at = 1; at <= (operation ? 4U : 5U); ++at) {
            memset(&fake, 0, sizeof(fake));
            tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32, write32, 4U);
            if (operation) fake.fail_write_at = at;
            else fake.fail_read_at = at;
            value = UINT32_C(0xfeedface);
            failures += expect(tiny3tpu_axis_mailbox_read32(&mailbox, 0, &value) != 0,
                               "each callback failure propagates");
            failures += expect(tiny3tpu_axis_mailbox_is_poisoned(&mailbox),
                               "each callback failure poisons");
            failures += expect(value == UINT32_C(0xfeedface),
                               "failed read leaves caller output unchanged");
            before = fake.reads + fake.writes;
            failures += expect(tiny3tpu_axis_mailbox_write32(&mailbox, 0, 1) != 0 &&
                               before == fake.reads + fake.writes,
                               "failed context cannot submit another command");
        }
    }
    for (unsigned code = 2; code <= 3; ++code) {
        memset(&fake, 0, sizeof(fake));
        fake.code = code;
        tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32, write32, 4U);
        tiny3tpu_mmio accelerator = {&mailbox, tiny3tpu_axis_mailbox_read32,
                                    tiny3tpu_axis_mailbox_write32, 4U};
        value = UINT32_C(0xfeedface);
        failures += expect(accelerator.read32(accelerator.user, 0, &value) != 0 &&
                           value == UINT32_C(0xfeedface), "AXI errors propagate without data");
        failures += expect(!tiny3tpu_axis_mailbox_is_poisoned(&mailbox) && fake.status == 0,
                           "retired AXI error is acknowledged, not poisoned");
        fake.code = 0;
        failures += expect(accelerator.write32(accelerator.user, 0, 1) == 0,
                           "valid command works following AXI error");
    }
    for (unsigned state = 1; state <= 2; ++state) {
        memset(&fake, 0, sizeof(fake));
        fake.status = state;
        tiny3tpu_axis_mailbox_init(&mailbox, &fake, read32, write32, 4U);
        failures += expect(tiny3tpu_axis_mailbox_read32(&mailbox, 0, &value) != 0 &&
                           fake.writes == 0 && tiny3tpu_axis_mailbox_is_poisoned(&mailbox),
                           "preexisting busy/result ownership is rejected");
    }
    memset(&fake, 0, sizeof(fake));
    tiny3tpu_mmio lowlevel = {&fake, read32, write32, 4U};
    failures += expect(tiny3tpu_axis_mailbox_init_from_mmio(&mailbox, &lowlevel) == 0,
                       "MMIO callback initializer succeeds");
    failures += expect(tiny3tpu_axis_mailbox_read32(&mailbox, 0x100, &value) != 0 &&
                       fake.reads == 0 && fake.writes == 0, "wide target offset cannot alias");
    failures += expect(tiny3tpu_axis_mailbox_read32(&mailbox, 0, NULL) != 0 &&
                       fake.reads == 0 && fake.writes == 0, "null output cannot access bus");

    if (failures != 0) return 1;
    puts("AXIS mailbox driver: callbacks, strobes, timeout and stale safety passed");
    return 0;
}
