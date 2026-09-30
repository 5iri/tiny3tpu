#include "tiny3tpu_runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    MODEL_BYTES = 384,
    TENSOR_TABLE_OFFSET = 80,
    OPERATION_TABLE_OFFSET = 224,
    PARAMETER_OFFSET = 304,
    CONSTANT_OFFSET = 336,
    ARENA_OFFSET = 336,
    ARENA_BYTES = 48
};

static void put_u32(uint8_t *bytes, uint32_t offset, uint32_t value)
{
    bytes[offset] = (uint8_t)value;
    bytes[offset + 1U] = (uint8_t)(value >> 8U);
    bytes[offset + 2U] = (uint8_t)(value >> 16U);
    bytes[offset + 3U] = (uint8_t)(value >> 24U);
}

static uint32_t crc32(const uint8_t *bytes, uint32_t length)
{
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    uint32_t index;

    for (index = 0U; index < length; ++index) {
        uint32_t value = bytes[index];
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

static void put_tensor(uint8_t *model, uint32_t index, uint8_t dtype,
                       uint8_t rank, uint8_t flags, uint32_t dim0,
                       uint32_t dim1, uint32_t byte_offset,
                       uint32_t byte_size)
{
    const uint32_t offset = TENSOR_TABLE_OFFSET +
                            index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
    put_u32(model, offset + TINY3TPU_TENSOR_ID_OFFSET, index);
    model[offset + TINY3TPU_TENSOR_META_OFFSET] = dtype;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 1U] = rank;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 2U] =
        TINY3TPU_LAYOUT_PACKED;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 3U] = flags;
    put_u32(model, offset + TINY3TPU_TENSOR_DIMS_OFFSET, dim0);
    put_u32(model, offset + TINY3TPU_TENSOR_DIMS_OFFSET + 4U, dim1);
    put_u32(model, offset + TINY3TPU_TENSOR_BYTE_OFFSET, byte_offset);
    put_u32(model, offset + TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, byte_size);
    put_u32(model, offset + TINY3TPU_TENSOR_SCALE_OFFSET,
            UINT32_C(0x3F800000));
}

static void put_operation(uint8_t *model, uint32_t index, uint32_t opcode,
                          uint32_t input, uint32_t output,
                          uint32_t parameter_offset)
{
    const uint32_t offset = OPERATION_TABLE_OFFSET +
                            index * TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
    put_u32(model, offset + TINY3TPU_OPERATION_OPCODE_OFFSET, opcode);
    put_u32(model, offset + TINY3TPU_OPERATION_VERSION_OFFSET,
            TINY3TPU_MODEL_VERSION);
    put_u32(model, offset + TINY3TPU_OPERATION_INPUTS_OFFSET, input);
    put_u32(model, offset + TINY3TPU_OPERATION_INPUTS_OFFSET + 4U,
            UINT32_MAX);
    put_u32(model, offset + TINY3TPU_OPERATION_INPUTS_OFFSET + 8U,
            UINT32_MAX);
    put_u32(model, offset + TINY3TPU_OPERATION_OUTPUTS_OFFSET, output);
    put_u32(model, offset + TINY3TPU_OPERATION_OUTPUTS_OFFSET + 4U,
            UINT32_MAX);
    put_u32(model, offset + TINY3TPU_OPERATION_PARAMETER_OFFSET,
            parameter_offset);
    put_u32(model, offset + TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET,
            opcode == TINY3TPU_OP_RESHAPE ?
                TINY3TPU_RESHAPE_PARAMETER_BYTES :
                TINY3TPU_ARGMAX_PARAMETER_BYTES);
}

static void build_model(uint8_t *model)
{
    memset(model, 0, MODEL_BYTES);
    put_u32(model, TINY3TPU_HEADER_MAGIC_OFFSET, TINY3TPU_MODEL_MAGIC);
    put_u32(model, TINY3TPU_HEADER_VERSION_OFFSET, TINY3TPU_MODEL_VERSION);
    put_u32(model, TINY3TPU_HEADER_BYTES_OFFSET,
            TINY3TPU_MODEL_HEADER_BYTES);
    put_u32(model, TINY3TPU_HEADER_TOTAL_BYTES_OFFSET, MODEL_BYTES);
    put_u32(model, TINY3TPU_HEADER_TENSOR_COUNT_OFFSET, 3U);
    put_u32(model, TINY3TPU_HEADER_OPERATION_COUNT_OFFSET, 2U);
    put_u32(model, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET,
            TENSOR_TABLE_OFFSET);
    put_u32(model, TINY3TPU_HEADER_OPERATION_TABLE_OFFSET,
            OPERATION_TABLE_OFFSET);
    put_u32(model, TINY3TPU_HEADER_PARAMETER_OFFSET, PARAMETER_OFFSET);
    put_u32(model, TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET, 32U);
    put_u32(model, TINY3TPU_HEADER_CONSTANT_OFFSET, CONSTANT_OFFSET);
    put_u32(model, TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET, 0U);
    put_u32(model, TINY3TPU_HEADER_ARENA_OFFSET, ARENA_OFFSET);
    put_u32(model, TINY3TPU_HEADER_ARENA_BYTES_OFFSET, ARENA_BYTES);
    put_u32(model, TINY3TPU_HEADER_INPUT_COUNT_OFFSET, 1U);
    put_u32(model, TINY3TPU_HEADER_OUTPUT_COUNT_OFFSET, 1U);

    put_tensor(model, 0U, TINY3TPU_DTYPE_I8, 2U, TINY3TPU_TENSOR_INPUT,
               2U, 2U, 336U, 4U);
    put_tensor(model, 1U, TINY3TPU_DTYPE_I8, 1U, 0U,
               4U, 0U, 352U, 4U);
    put_tensor(model, 2U, TINY3TPU_DTYPE_I32, 1U, TINY3TPU_TENSOR_OUTPUT,
               1U, 0U, 368U, 4U);

    put_operation(model, 0U, TINY3TPU_OP_RESHAPE, 0U, 1U, 304U);
    put_operation(model, 1U, TINY3TPU_OP_ARGMAX, 1U, 2U, 328U);
    put_u32(model, 304U, 1U);
    put_u32(model, 308U, 4U);
    put_u32(model, 312U, 0U);
    put_u32(model, 316U, 0U);
    put_u32(model, 320U, 0U);
    put_u32(model, 324U, 0U);
    put_u32(model, 328U, 0U);
    put_u32(model, 332U, 0U);
    put_u32(model, TINY3TPU_HEADER_CRC32_OFFSET, crc32(model, MODEL_BYTES));
}

static int run_model(uint8_t *model, uint8_t *workspace, int8_t *input,
                     int32_t *output)
{
    tiny3tpu_runtime runtime;

    if (tiny3tpu_runtime_init(&runtime, NULL) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_load_model(&runtime, model, MODEL_BYTES) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_bind_workspace(&runtime, workspace, ARENA_BYTES) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_bind_input(&runtime, 0U, input, 4U) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_run(&runtime) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_read_output(&runtime, 2U, output, 1U) !=
            TINY3TPU_RUNTIME_OK)
        return 0;
    return output[0] == 1 && workspace[352U - ARENA_OFFSET] == 0xFE &&
           workspace[353U - ARENA_OFFSET] == 7U &&
           workspace[354U - ARENA_OFFSET] == 1U &&
           workspace[355U - ARENA_OFFSET] == 7U;
}

int main(void)
{
    uint8_t model[MODEL_BYTES];
    uint8_t modified[MODEL_BYTES];
    uint8_t workspace[ARENA_BYTES];
    int8_t input[4] = {-2, 7, 1, 7};
    int32_t output[1] = {0};
    tiny3tpu_runtime runtime;

    build_model(model);
    if (!run_model(model, workspace, input, output)) return 1;

    /* Axis 1 is a valid wire shape but outside the runtime subset. */
    memcpy(modified, model, sizeof(modified));
    put_u32(modified, 328U, 1U);
    put_u32(modified, TINY3TPU_HEADER_CRC32_OFFSET,
            crc32(modified, MODEL_BYTES));
    if (tiny3tpu_runtime_init(&runtime, NULL) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_load_model(&runtime, modified, MODEL_BYTES) !=
            TINY3TPU_RUNTIME_BAD_MODEL)
        return 2;

    /* RESHAPE and ARGMAX reject non-packed storage at execution time. */
    memcpy(modified, model, sizeof(modified));
    modified[TENSOR_TABLE_OFFSET + TINY3TPU_TENSOR_META_OFFSET + 2U] =
        TINY3TPU_LAYOUT_NHWC;
    put_u32(modified, TINY3TPU_HEADER_CRC32_OFFSET,
            crc32(modified, MODEL_BYTES));
    if (tiny3tpu_runtime_init(&runtime, NULL) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_load_model(&runtime, modified, MODEL_BYTES) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_bind_workspace(&runtime, workspace, ARENA_BYTES) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_bind_input(&runtime, 0U, input, 4U) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_run(&runtime) != TINY3TPU_RUNTIME_UNSUPPORTED)
        return 3;

    (void)printf("runtime RESHAPE/ARGMAX tests passed\n");
    return 0;
}
