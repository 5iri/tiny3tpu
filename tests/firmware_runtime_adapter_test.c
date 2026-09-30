#include "tiny3tpu_firmware_runtime_adapter.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { MODEL_BYTES = 608, INPUT_BYTES = 2, WORKSPACE_BYTES = 48 };

typedef struct test_stream {
    uint8_t request[MODEL_BYTES + 32U];
    uint32_t request_bytes;
    uint32_t request_pos;
    uint8_t response[MODEL_BYTES + 64U];
    uint32_t response_bytes;
} test_stream;

static void put_u32(uint8_t *data, uint32_t offset, uint32_t value)
{
    data[offset] = (uint8_t)value;
    data[offset + 1U] = (uint8_t)(value >> 8U);
    data[offset + 2U] = (uint8_t)(value >> 16U);
    data[offset + 3U] = (uint8_t)(value >> 24U);
}

static uint32_t crc32(const uint8_t *data, uint32_t length)
{
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    uint32_t index;

    for (index = 0U; index < length; ++index) {
        uint32_t value = data[index];
        uint32_t bit;
        if (index >= TINY3TPU_HEADER_CRC32_OFFSET &&
            index < TINY3TPU_HEADER_CRC32_OFFSET + 4U)
            value = 0U;
        crc ^= value;
        for (bit = 0U; bit < 8U; ++bit)
            crc = (crc >> 1U) ^
                  (UINT32_C(0xEDB88320) & (UINT32_C(0) - (crc & 1U)));
    }
    return ~crc;
}

static int read_u8(void *user, uint8_t *value)
{
    test_stream *stream = (test_stream *)user;
    if (stream->request_pos >= stream->request_bytes) return -1;
    *value = stream->request[stream->request_pos++];
    return 0;
}

static int write_u8(void *user, uint8_t value)
{
    test_stream *stream = (test_stream *)user;
    if (stream->response_bytes >= sizeof(stream->response)) return -1;
    stream->response[stream->response_bytes++] = value;
    return 0;
}

static void request_reset(test_stream *stream)
{
    stream->request_pos = 0U;
    stream->response_bytes = 0U;
}

static void request_command(test_stream *stream, uint32_t command)
{
    put_u32(stream->request, 0U, command);
    stream->request_bytes = 4U;
    request_reset(stream);
}

static int response_status(const test_stream *stream, int32_t *status,
                           uint32_t *count)
{
    if (stream->response_bytes < 12U ||
        ((uint32_t)stream->response[0] |
         ((uint32_t)stream->response[1] << 8U) |
         ((uint32_t)stream->response[2] << 16U) |
         ((uint32_t)stream->response[3] << 24U)) !=
            TINY3TPU_FIRMWARE_RUNTIME_RESPONSE_MAGIC)
        return 0;
    *status = (int32_t)((uint32_t)stream->response[4] |
                        ((uint32_t)stream->response[5] << 8U) |
                        ((uint32_t)stream->response[6] << 16U) |
                        ((uint32_t)stream->response[7] << 24U));
    *count = (uint32_t)stream->response[8] |
             ((uint32_t)stream->response[9] << 8U) |
             ((uint32_t)stream->response[10] << 16U) |
             ((uint32_t)stream->response[11] << 24U);
    return 1;
}

/* The model is the same two-QGEMM fixture used by runtime_smoke.c. */
static void make_model(uint8_t *model)
{
    uint32_t i;
    memset(model, 0, MODEL_BYTES);
#define U32(o, v) put_u32(model, (o), (v))
    U32(0U, TINY3TPU_MODEL_MAGIC); U32(4U, TINY3TPU_MODEL_VERSION);
    U32(8U, 80U); U32(12U, MODEL_BYTES); U32(16U, 7U); U32(20U, 2U);
    U32(24U, 80U); U32(28U, 416U); U32(32U, 496U); U32(36U, 32U);
    U32(40U, 528U); U32(44U, 32U); U32(48U, 560U); U32(52U, 48U);
    U32(56U, 0U); U32(60U, 0U); U32(64U, 1U); U32(68U, 2U);
    for (i = 0U; i < 7U; ++i) {
        uint32_t o = 80U + i * 48U;
        U32(o, i); model[o + 4U] = i == 0U ? TINY3TPU_DTYPE_I8 :
            (i == 1U || i == 4U ? TINY3TPU_DTYPE_I8 : TINY3TPU_DTYPE_I32);
        model[o + 5U] = (i == 2U || i == 5U) ? 1U : 2U;
        model[o + 6U] = TINY3TPU_LAYOUT_PACKED;
        model[o + 7U] = i == 0U ? TINY3TPU_TENSOR_INPUT :
            ((i == 1U || i == 2U || i == 4U || i == 5U) ?
                TINY3TPU_TENSOR_CONSTANT : TINY3TPU_TENSOR_OUTPUT);
        U32(o + 8U, (i == 0U || i == 3U || i == 6U) ? 1U : 2U);
        U32(o + 12U, (i == 2U || i == 5U) ? 0U : 2U);
        U32(o + 24U, i == 0U ? 560U : (i == 1U ? 528U : i == 2U ? 532U :
            i == 3U ? 576U : i == 4U ? 540U : i == 5U ? 544U : 592U));
        U32(o + 28U, i == 0U ? 2U :
            ((i == 1U || i == 4U) ? 4U : 8U));
        U32(o + 32U, UINT32_C(0x3F800000));
    }
    for (i = 0U; i < 2U; ++i) {
        uint32_t o = 416U + i * 40U;
        U32(o, TINY3TPU_OP_QGEMM); U32(o + 4U, TINY3TPU_MODEL_VERSION);
        U32(o + 8U, 0U); U32(o + 12U, i == 0U ? 1U : 4U);
        U32(o + 16U, i == 0U ? 2U : 5U); U32(o + 20U, i == 0U ? 3U : 6U);
        U32(o + 24U, UINT32_MAX); U32(o + 28U, 496U + i * 16U);
        U32(o + 32U, 16U); U32(o + 36U, 0U);
    }
    model[528U] = 1U; model[529U] = 2U; model[530U] = 3U; model[531U] = 4U;
    U32(532U, 1U); U32(536U, UINT32_C(0xFFFFFFFE));
    model[540U] = 2U; model[541U] = 0U; model[542U] = UINT8_C(0xFF); model[543U] = 1U;
    U32(544U, 0U); U32(548U, 5U);
    U32(TINY3TPU_HEADER_CRC32_OFFSET, crc32(model, MODEL_BYTES));
#undef U32
}

int main(void)
{
    uint8_t model[MODEL_BYTES];
    uint8_t model_storage[MODEL_BYTES];
    uint8_t model_staging[MODEL_BYTES];
    uint8_t workspace[WORKSPACE_BYTES];
    int8_t input[INPUT_BYTES] = {3, -4};
    int32_t output[2];
    test_stream stream;
    tiny3tpu_firmware_runtime_adapter adapter;
    tiny3tpu_firmware_runtime_adapter_config config;
    tiny3tpu_firmware_runtime_io io;
    int32_t status;
    uint32_t count;

    memset(&stream, 0, sizeof(stream));
    make_model(model);
    memset(&config, 0, sizeof(config));
    config.model_storage = model_storage; config.model_capacity = sizeof(model_storage);
    config.model_staging = model_staging;
    config.workspace = workspace; config.workspace_capacity = sizeof(workspace);
    config.input_storage = input; config.input_capacity = sizeof(input);
    config.output_storage = output; config.output_capacity_elements = 2U;
    if (tiny3tpu_firmware_runtime_adapter_init(&adapter, &config) != 0) return 1;
    io.user = &stream; io.read_u8 = read_u8; io.write_u8 = write_u8;

    request_command(&stream, TINY3TPU_FIRMWARE_RUNTIME_LOAD);
    put_u32(stream.request, 4U, MODEL_BYTES);
    memcpy(stream.request + 8U, model, MODEL_BYTES);
    stream.request_bytes = 8U + MODEL_BYTES;
    if (tiny3tpu_firmware_runtime_handle_command(&adapter, &io) != 0 ||
        !response_status(&stream, &status, &count) || status != 0 || count != 0U)
        return 2;

    request_command(&stream, TINY3TPU_FIRMWARE_RUNTIME_BIND_INPUT);
    put_u32(stream.request, 4U, 0U);
    put_u32(stream.request, 8U, INPUT_BYTES);
    memcpy(stream.request + 12U, input, INPUT_BYTES);
    stream.request_bytes = 12U + INPUT_BYTES;
    if (tiny3tpu_firmware_runtime_handle_command(&adapter, &io) != 0 ||
        !response_status(&stream, &status, &count) || status != 0 || count != 0U)
        return 3;

    request_command(&stream, TINY3TPU_FIRMWARE_RUNTIME_RUN);
    if (tiny3tpu_firmware_runtime_handle_command(&adapter, &io) != 0 ||
        !response_status(&stream, &status, &count) || status != 0 || count != 0U)
        return 4;

    request_command(&stream, TINY3TPU_FIRMWARE_RUNTIME_READ_OUTPUT);
    put_u32(stream.request, 4U, 3U);
    put_u32(stream.request, 8U, 2U);
    stream.request_bytes = 12U;
    if (tiny3tpu_firmware_runtime_handle_command(&adapter, &io) != 0 ||
        !response_status(&stream, &status, &count) || status != 0 || count != 2U)
        return 5;
    if ((int32_t)((uint32_t)stream.response[12] |
                  ((uint32_t)stream.response[13] << 8U) |
                  ((uint32_t)stream.response[14] << 16U) |
                  ((uint32_t)stream.response[15] << 24U)) != -4 ||
        (int32_t)((uint32_t)stream.response[16] |
                  ((uint32_t)stream.response[17] << 8U) |
                  ((uint32_t)stream.response[18] << 16U) |
                  ((uint32_t)stream.response[19] << 24U)) != -9)
        return 6;

    request_command(&stream, TINY3TPU_FIRMWARE_RUNTIME_READ_OUTPUT);
    put_u32(stream.request, 4U, 6U);
    put_u32(stream.request, 8U, 2U);
    stream.request_bytes = 12U;
    if (tiny3tpu_firmware_runtime_handle_command(&adapter, &io) != 0 ||
        !response_status(&stream, &status, &count) || status != 0 || count != 2U)
        return 7;
    if ((int32_t)((uint32_t)stream.response[12] |
                  ((uint32_t)stream.response[13] << 8U) |
                  ((uint32_t)stream.response[14] << 16U) |
                  ((uint32_t)stream.response[15] << 24U)) != 6 ||
        (int32_t)((uint32_t)stream.response[16] |
                  ((uint32_t)stream.response[17] << 8U) |
                  ((uint32_t)stream.response[18] << 16U) |
                  ((uint32_t)stream.response[19] << 24U)) != -2)
        return 8;
    (void)printf("firmware runtime adapter smoke passed\n");
    return 0;
}
