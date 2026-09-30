#include "tiny3tpu_runtime.h"

#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    MODEL_BYTES = 368,
    TENSOR_TABLE_OFFSET = 80,
    OPERATION_TABLE_OFFSET = 272,
    PARAMETER_OFFSET = 312,
    CONSTANT_OFFSET = 328,
    ARENA_OFFSET = 336,
    ARENA_BYTES = 32
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
                       uint8_t flags, uint32_t dim0, uint32_t dim1,
                       uint32_t byte_offset, uint32_t byte_size,
                       uint32_t scale_bits)
{
    const uint32_t offset = TENSOR_TABLE_OFFSET +
                            index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;

    put_u32(model, offset + TINY3TPU_TENSOR_ID_OFFSET, index);
    model[offset + TINY3TPU_TENSOR_META_OFFSET] = dtype;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 1U] =
        index == 2U ? 1U : 2U;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 2U] =
        TINY3TPU_LAYOUT_PACKED;
    model[offset + TINY3TPU_TENSOR_META_OFFSET + 3U] = flags;
    put_u32(model, offset + TINY3TPU_TENSOR_DIMS_OFFSET, dim0);
    put_u32(model, offset + TINY3TPU_TENSOR_DIMS_OFFSET + 4U, dim1);
    put_u32(model, offset + TINY3TPU_TENSOR_BYTE_OFFSET, byte_offset);
    put_u32(model, offset + TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, byte_size);
    put_u32(model, offset + TINY3TPU_TENSOR_SCALE_OFFSET, scale_bits);
}

static void build_model(uint8_t *model, uint8_t output_dtype,
                        uint32_t flags, int32_t multiplier, uint32_t shift,
                        uint32_t input_scale, uint32_t weight_scale,
                        uint32_t bias_scale, uint32_t output_scale)
{
    const uint32_t output_bytes = output_dtype == TINY3TPU_DTYPE_I32 ? 4U : 1U;

    memset(model, 0, MODEL_BYTES);
    put_u32(model, TINY3TPU_HEADER_MAGIC_OFFSET, TINY3TPU_MODEL_MAGIC);
    put_u32(model, TINY3TPU_HEADER_VERSION_OFFSET, TINY3TPU_MODEL_VERSION);
    put_u32(model, TINY3TPU_HEADER_BYTES_OFFSET,
            TINY3TPU_MODEL_HEADER_BYTES);
    put_u32(model, TINY3TPU_HEADER_TOTAL_BYTES_OFFSET, MODEL_BYTES);
    put_u32(model, TINY3TPU_HEADER_TENSOR_COUNT_OFFSET, 4U);
    put_u32(model, TINY3TPU_HEADER_OPERATION_COUNT_OFFSET, 1U);
    put_u32(model, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET, TENSOR_TABLE_OFFSET);
    put_u32(model, TINY3TPU_HEADER_OPERATION_TABLE_OFFSET,
            OPERATION_TABLE_OFFSET);
    put_u32(model, TINY3TPU_HEADER_PARAMETER_OFFSET, PARAMETER_OFFSET);
    put_u32(model, TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET, 16U);
    put_u32(model, TINY3TPU_HEADER_CONSTANT_OFFSET, CONSTANT_OFFSET);
    put_u32(model, TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET, 8U);
    put_u32(model, TINY3TPU_HEADER_ARENA_OFFSET, ARENA_OFFSET);
    put_u32(model, TINY3TPU_HEADER_ARENA_BYTES_OFFSET, ARENA_BYTES);
    put_u32(model, TINY3TPU_HEADER_INPUT_COUNT_OFFSET, 1U);
    put_u32(model, TINY3TPU_HEADER_OUTPUT_COUNT_OFFSET, 1U);

    put_tensor(model, 0U, TINY3TPU_DTYPE_I8, TINY3TPU_TENSOR_INPUT,
               1U, 1U, 336U, 1U, input_scale);
    put_tensor(model, 1U, TINY3TPU_DTYPE_I8, TINY3TPU_TENSOR_CONSTANT,
               1U, 1U, 328U, 1U, weight_scale);
    put_tensor(model, 2U, TINY3TPU_DTYPE_I32, TINY3TPU_TENSOR_CONSTANT,
               1U, 0U, 332U, 4U, bias_scale);
    put_tensor(model, 3U, output_dtype, TINY3TPU_TENSOR_OUTPUT,
               1U, 1U, 352U, output_bytes, output_scale);

    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_OPCODE_OFFSET,
            TINY3TPU_OP_QGEMM);
    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_VERSION_OFFSET,
            TINY3TPU_MODEL_VERSION);
    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_INPUTS_OFFSET,
            0U);
    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_INPUTS_OFFSET +
            4U, 1U);
    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_INPUTS_OFFSET +
            8U, 2U);
    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_OUTPUTS_OFFSET,
            3U);
    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_OUTPUTS_OFFSET +
            4U, UINT32_MAX);
    put_u32(model, OPERATION_TABLE_OFFSET + TINY3TPU_OPERATION_PARAMETER_OFFSET,
            PARAMETER_OFFSET);
    put_u32(model, OPERATION_TABLE_OFFSET +
            TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET, 16U);

    put_u32(model, PARAMETER_OFFSET, (uint32_t)multiplier);
    put_u32(model, PARAMETER_OFFSET + 4U, shift);
    put_u32(model, PARAMETER_OFFSET + 8U, flags);
    put_u32(model, CONSTANT_OFFSET, 1U);
    put_u32(model, CONSTANT_OFFSET + 4U, 0U); /* bias = 0 */
    put_u32(model, TINY3TPU_HEADER_CRC32_OFFSET, crc32(model, MODEL_BYTES));
}

static int expect_load_failure(const uint8_t *model)
{
    tiny3tpu_runtime runtime;

    if (tiny3tpu_runtime_init(&runtime, NULL) != TINY3TPU_RUNTIME_OK)
        return 0;
    return tiny3tpu_runtime_load_model(&runtime, model, MODEL_BYTES) ==
           TINY3TPU_RUNTIME_BAD_MODEL;
}

static int run_valid_model(const uint8_t *model, uint32_t flags,
                           int32_t expected)
{
    uint8_t workspace[ARENA_BYTES];
    int8_t input[1] = {-4};
    int32_t output[1] = {0};
    tiny3tpu_runtime runtime;

    if (tiny3tpu_runtime_init(&runtime, NULL) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_load_model(&runtime, model, MODEL_BYTES) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_bind_workspace(&runtime, workspace,
                                        sizeof(workspace)) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_bind_input(&runtime, 0U, input, sizeof(input)) !=
            TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_run(&runtime) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_read_output(&runtime, 3U, output, 1U) !=
            TINY3TPU_RUNTIME_OK || output[0] != expected)
        return 0;
    (void)flags;
    return 1;
}

static int load_external_model(const char *path)
{
    FILE *file;
    long file_size;
    uint8_t *bytes;
    tiny3tpu_runtime runtime;
    int result;

    file = fopen(path, "rb");
    if (file == NULL || fseek(file, 0L, SEEK_END) != 0) {
        if (file != NULL) (void)fclose(file);
        return 0;
    }
    file_size = ftell(file);
    if (file_size <= 0L || fseek(file, 0L, SEEK_SET) != 0) {
        (void)fclose(file);
        return 0;
    }
    bytes = (uint8_t *)malloc((size_t)file_size);
    if (bytes == NULL || fread(bytes, 1U, (size_t)file_size, file) !=
                            (size_t)file_size) {
        free(bytes);
        (void)fclose(file);
        return 0;
    }
    (void)fclose(file);
    result = tiny3tpu_runtime_init(&runtime, NULL) == TINY3TPU_RUNTIME_OK &&
             tiny3tpu_runtime_load_model(&runtime, bytes,
                                         (uint32_t)file_size) ==
                 TINY3TPU_RUNTIME_OK;
    free(bytes);
    return result;
}

int main(int argc, char **argv)
{
    uint8_t model[MODEL_BYTES];

    if (argc == 2) {
        if (!load_external_model(argv[1])) return 7;
        (void)printf("external model load passed\n");
        return 0;
    }
    if (argc != 1) return 8;

    /* -4 * 1 with multiplier=1, shift=1 is exactly -2. */
    build_model(model, TINY3TPU_DTYPE_I8, TINY3TPU_QGEMM_FLAG_REQUANT,
                1, 1U, UINT32_C(0x3F800000), UINT32_C(0x3F800000),
                UINT32_C(0x3F800000), UINT32_C(0x40000000));
    if (!run_valid_model(model, TINY3TPU_QGEMM_FLAG_REQUANT, -2)) return 1;

    /* ReLU remains valid for int8 requantized results. */
    build_model(model, TINY3TPU_DTYPE_I8,
                TINY3TPU_QGEMM_FLAG_REQUANT | TINY3TPU_QGEMM_FLAG_RELU,
                1, 1U, UINT32_C(0x3F800000), UINT32_C(0x3F800000),
                UINT32_C(0x3F800000), UINT32_C(0x40000000));
    if (!run_valid_model(model, TINY3TPU_QGEMM_FLAG_REQUANT |
                                  TINY3TPU_QGEMM_FLAG_RELU, 0)) return 2;

    build_model(model, TINY3TPU_DTYPE_I32, TINY3TPU_QGEMM_FLAG_REQUANT,
                1, 1U, UINT32_C(0x3F800000), UINT32_C(0x3F800000),
                UINT32_C(0x3F800000), UINT32_C(0x40000000));
    if (!expect_load_failure(model)) return 3;

    build_model(model, TINY3TPU_DTYPE_I8, TINY3TPU_QGEMM_FLAG_REQUANT,
                2, 1U, UINT32_C(0x3F800000), UINT32_C(0x3F800000),
                UINT32_C(0x3F800000), UINT32_C(0x40000000));
    if (!expect_load_failure(model)) return 4;

    build_model(model, TINY3TPU_DTYPE_I8, TINY3TPU_QGEMM_FLAG_REQUANT,
                1, 1U, UINT32_C(0x3F800000), UINT32_C(0x3F800000),
                UINT32_C(0x40000000), UINT32_C(0x40000000));
    if (!expect_load_failure(model)) return 5;

    /* FLT_MAX * FLT_MAX cannot be represented as a model float scale. */
    build_model(model, TINY3TPU_DTYPE_I8, TINY3TPU_QGEMM_FLAG_REQUANT,
                1, 1U, UINT32_C(0x7F7FFFFF), UINT32_C(0x7F7FFFFF),
                UINT32_C(0x7F7FFFFF), UINT32_C(0x3F800000));
    if (!expect_load_failure(model)) return 6;

    (void)printf("runtime requantization tests passed\n");
    return 0;
}
