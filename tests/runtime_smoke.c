#include "tiny3tpu_runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    MODEL_BYTES = 608,
    TENSOR_TABLE_OFFSET = 80,
    OPERATION_TABLE_OFFSET = 416,
    PARAMETER_OFFSET = 496,
    CONSTANT_OFFSET = 528,
    ARENA_OFFSET = 560,
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

static void put_tensor(uint8_t *model, uint32_t index, uint32_t id,
                       uint8_t dtype, uint8_t rank, uint8_t flags,
                       uint32_t dim0, uint32_t dim1,
                       uint32_t byte_offset, uint32_t byte_size)
{
    const uint32_t offset = TENSOR_TABLE_OFFSET +
                            index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
    put_u32(model, offset + TINY3TPU_TENSOR_ID_OFFSET, id);
    model[offset + TINY3TPU_TENSOR_META_OFFSET] = dtype;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 1U] = rank;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 2U] = TINY3TPU_LAYOUT_PACKED;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 3U] = flags;
    put_u32(model, offset + TINY3TPU_TENSOR_DIMS_OFFSET, dim0);
    put_u32(model, offset + TINY3TPU_TENSOR_DIMS_OFFSET + 4U, dim1);
    put_u32(model, offset + TINY3TPU_TENSOR_BYTE_OFFSET, byte_offset);
    put_u32(model, offset + TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, byte_size);
    put_u32(model, offset + TINY3TPU_TENSOR_SCALE_OFFSET,
            UINT32_C(0x3F800000));
}

static void put_operation(uint8_t *model, uint32_t index,
                          uint32_t input0, uint32_t input1, uint32_t input2,
                          uint32_t output, uint32_t parameter_offset)
{
    const uint32_t offset = OPERATION_TABLE_OFFSET +
                            index * TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
    put_u32(model, offset + TINY3TPU_OPERATION_OPCODE_OFFSET,
            TINY3TPU_OP_QGEMM);
    put_u32(model, offset + TINY3TPU_OPERATION_VERSION_OFFSET,
            TINY3TPU_MODEL_VERSION);
    put_u32(model, offset + TINY3TPU_OPERATION_INPUTS_OFFSET, input0);
    put_u32(model, offset + TINY3TPU_OPERATION_INPUTS_OFFSET + 4U, input1);
    put_u32(model, offset + TINY3TPU_OPERATION_INPUTS_OFFSET + 8U, input2);
    put_u32(model, offset + TINY3TPU_OPERATION_OUTPUTS_OFFSET, output);
    put_u32(model, offset + TINY3TPU_OPERATION_OUTPUTS_OFFSET + 4U,
            UINT32_MAX);
    put_u32(model, offset + TINY3TPU_OPERATION_PARAMETER_OFFSET,
            parameter_offset);
    put_u32(model, offset + TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET, 16U);
}

static void build_model(uint8_t *model)
{
    memset(model, 0, MODEL_BYTES);

    put_u32(model, TINY3TPU_HEADER_MAGIC_OFFSET, TINY3TPU_MODEL_MAGIC);
    put_u32(model, TINY3TPU_HEADER_VERSION_OFFSET, TINY3TPU_MODEL_VERSION);
    put_u32(model, TINY3TPU_HEADER_BYTES_OFFSET,
            TINY3TPU_MODEL_HEADER_BYTES);
    put_u32(model, TINY3TPU_HEADER_TOTAL_BYTES_OFFSET, MODEL_BYTES);
    put_u32(model, TINY3TPU_HEADER_TENSOR_COUNT_OFFSET, 7U);
    put_u32(model, TINY3TPU_HEADER_OPERATION_COUNT_OFFSET, 2U);
    put_u32(model, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET,
            TENSOR_TABLE_OFFSET);
    put_u32(model, TINY3TPU_HEADER_OPERATION_TABLE_OFFSET,
            OPERATION_TABLE_OFFSET);
    put_u32(model, TINY3TPU_HEADER_PARAMETER_OFFSET, PARAMETER_OFFSET);
    put_u32(model, TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET, 32U);
    put_u32(model, TINY3TPU_HEADER_CONSTANT_OFFSET, CONSTANT_OFFSET);
    put_u32(model, TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET, 32U);
    put_u32(model, TINY3TPU_HEADER_ARENA_OFFSET, ARENA_OFFSET);
    put_u32(model, TINY3TPU_HEADER_ARENA_BYTES_OFFSET, ARENA_BYTES);
    put_u32(model, TINY3TPU_HEADER_INPUT_COUNT_OFFSET, 1U);
    put_u32(model, TINY3TPU_HEADER_OUTPUT_COUNT_OFFSET, 2U);

    put_tensor(model, 0U, 0U, TINY3TPU_DTYPE_I8, 2U,
               TINY3TPU_TENSOR_INPUT, 1U, 2U, 560U, 2U);
    put_tensor(model, 1U, 1U, TINY3TPU_DTYPE_I8, 2U,
               TINY3TPU_TENSOR_CONSTANT, 2U, 2U, 528U, 4U);
    put_tensor(model, 2U, 2U, TINY3TPU_DTYPE_I32, 1U,
               TINY3TPU_TENSOR_CONSTANT, 2U, 0U, 532U, 8U);
    put_tensor(model, 3U, 3U, TINY3TPU_DTYPE_I32, 2U,
               TINY3TPU_TENSOR_OUTPUT, 1U, 2U, 576U, 8U);
    put_tensor(model, 4U, 4U, TINY3TPU_DTYPE_I8, 2U,
               TINY3TPU_TENSOR_CONSTANT, 2U, 2U, 540U, 4U);
    put_tensor(model, 5U, 5U, TINY3TPU_DTYPE_I32, 1U,
               TINY3TPU_TENSOR_CONSTANT, 2U, 0U, 544U, 8U);
    put_tensor(model, 6U, 6U, TINY3TPU_DTYPE_I32, 2U,
               TINY3TPU_TENSOR_OUTPUT, 1U, 2U, 592U, 8U);

    put_operation(model, 0U, 0U, 1U, 2U, 3U, 496U);
    put_operation(model, 1U, 0U, 4U, 5U, 6U, 512U);

    /* Both operations use the int32, non-requantized parameter form. The
     * constants are stored explicitly as packed [N,K] int8 weights and
     * packed int32 biases. */
    model[528U] = 1U;
    model[529U] = 2U;
    model[530U] = 3U;
    model[531U] = 4U;
    put_u32(model, 532U, 1U);
    put_u32(model, 536U, UINT32_C(0xFFFFFFFE));
    model[540U] = 2U;
    model[541U] = 0U;
    model[542U] = UINT8_C(0xFF);
    model[543U] = 1U;
    put_u32(model, 544U, 0U);
    put_u32(model, 548U, 5U);
    put_u32(model, TINY3TPU_HEADER_CRC32_OFFSET, crc32(model, MODEL_BYTES));
}

int main(void)
{
    uint8_t model[MODEL_BYTES];
    uint8_t workspace[ARENA_BYTES];
    int8_t input[2] = {3, -4};
    int32_t output[2];
    tiny3tpu_runtime runtime;
    tiny3tpu_qgemm_backend backend = {0, 0};

    build_model(model);
    if (tiny3tpu_runtime_init(&runtime, &backend) != TINY3TPU_RUNTIME_OK)
        return 1;
    if (tiny3tpu_runtime_run(&runtime) != TINY3TPU_RUNTIME_NOT_READY)
        return 2;
    if (tiny3tpu_runtime_load_model(&runtime, model, MODEL_BYTES) !=
        TINY3TPU_RUNTIME_OK)
        return 3;
    if (tiny3tpu_runtime_bind_workspace(&runtime, workspace, 16U) !=
        TINY3TPU_RUNTIME_OK)
        return 4;
    if (tiny3tpu_runtime_bind_input(&runtime, 0U, input, sizeof(input)) !=
        TINY3TPU_RUNTIME_OK)
        return 5;
    if (tiny3tpu_runtime_run(&runtime) != TINY3TPU_RUNTIME_NO_MEMORY)
        return 6;
    if (tiny3tpu_runtime_bind_workspace(&runtime, workspace, sizeof(workspace)) !=
        TINY3TPU_RUNTIME_OK)
        return 7;
    if (tiny3tpu_runtime_run(&runtime) != TINY3TPU_RUNTIME_OK)
        return 8;
    if (tiny3tpu_runtime_read_output(&runtime, 3U, output, 2U) !=
        TINY3TPU_RUNTIME_OK || output[0] != -4 || output[1] != -9)
        return 9;
    if (tiny3tpu_runtime_read_output(&runtime, 6U, output, 2U) !=
        TINY3TPU_RUNTIME_OK || output[0] != 6 || output[1] != -2)
        return 10;
    (void)printf("runtime QGEMM smoke passed\n");
    return 0;
}
