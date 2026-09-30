#include "tiny3tpu_runtime.h"

#include <float.h>
#include <limits.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static uint32_t read_u32(const uint8_t *bytes, uint32_t offset)
{
    return ((uint32_t)bytes[offset]) |
           ((uint32_t)bytes[offset + 1U] << 8U) |
           ((uint32_t)bytes[offset + 2U] << 16U) |
           ((uint32_t)bytes[offset + 3U] << 24U);
}

static int range_is_inside(uint32_t offset, uint32_t length,
                           uint32_t total_bytes)
{
    return offset <= total_bytes && length <= total_bytes - offset;
}

static int section_end(uint32_t offset, uint32_t length,
                       uint32_t total_bytes, uint32_t *end)
{
    if (end == NULL || !range_is_inside(offset, length, total_bytes)) {
        return 0;
    }
    *end = offset + length;
    return 1;
}

static int ranges_overlap(uint32_t lhs_offset, uint32_t lhs_end,
                          uint32_t rhs_offset, uint32_t rhs_end)
{
    return lhs_offset < rhs_end && rhs_offset < lhs_end;
}

static int tensor_id_index(const uint8_t *model,
                           const tiny3tpu_model_header_view *header,
                           uint32_t tensor_id, uint32_t *index)
{
    uint32_t candidate;

    if (model == NULL || header == NULL) return 0;
    for (candidate = 0U; candidate < header->tensor_count; ++candidate) {
        const uint8_t *record = model + header->tensor_table_offset +
                                candidate * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
        if (read_u32(record, TINY3TPU_TENSOR_ID_OFFSET) == tensor_id) {
            if (index != NULL) *index = candidate;
            return 1;
        }
    }
    return 0;
}

static int tensor_is_produced_before(const uint8_t *model,
                                     const tiny3tpu_model_header_view *header,
                                     uint32_t operation_index, uint32_t tensor_id)
{
    uint32_t candidate;

    for (candidate = 0U; candidate < operation_index; ++candidate) {
        const uint8_t *record = model + header->operation_table_offset +
                                candidate * TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
        if (read_u32(record, TINY3TPU_OPERATION_OUTPUTS_OFFSET) == tensor_id) {
            return 1;
        }
    }
    return 0;
}

static int tensor_is_available(const uint8_t *model,
                               const tiny3tpu_model_header_view *header,
                               uint32_t operation_index, uint32_t tensor_id)
{
    uint32_t index;
    const uint8_t *record;
    uint8_t flags;

    if (!tensor_id_index(model, header, tensor_id, &index)) return 0;
    record = model + header->tensor_table_offset +
             index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
    flags = record[TINY3TPU_TENSOR_META_OFFSET + 3U];
    return (flags & (TINY3TPU_TENSOR_INPUT | TINY3TPU_TENSOR_CONSTANT)) != 0U ||
           tensor_is_produced_before(model, header, operation_index, tensor_id);
}

static int tensor_byte_size(uint8_t dtype, const uint32_t *dims,
                            uint8_t rank, uint32_t *byte_size)
{
    uint64_t elements = 1U;
    uint32_t index;
    uint32_t element_bytes;

    if (dims == NULL || byte_size == NULL || rank == 0U ||
        rank > TINY3TPU_MAX_RANK) return 0;
    if (dtype == TINY3TPU_DTYPE_I32) element_bytes = 4U;
    else if (dtype == TINY3TPU_DTYPE_I8 || dtype == TINY3TPU_DTYPE_U8)
        element_bytes = 1U;
    else return 0;
    for (index = 0U; index < rank; ++index) {
        if (dims[index] == 0U) return 0;
        elements *= dims[index];
        if (elements > UINT32_MAX) return 0;
    }
    if (elements > UINT32_MAX / element_bytes) return 0;
    *byte_size = (uint32_t)elements * element_bytes;
    return 1;
}

static int positive_finite_scale_bits(uint32_t bits)
{
    const uint32_t exponent = (bits >> 23U) & UINT32_C(0xFF);
    const uint32_t mantissa = bits & UINT32_C(0x7FFFFF);
    return (bits & UINT32_C(0x80000000)) == 0U && bits != 0U &&
           !(exponent == UINT32_C(0xFF) && mantissa != 0U) &&
           exponent != UINT32_C(0xFF);
}

static float scale_from_bits(uint32_t bits)
{
    float value;

    memcpy(&value, &bits, sizeof(value));
    return value;
}

static int scales_match(float lhs, float rhs)
{
    const double left = (double)lhs;
    const double right = (double)rhs;
    const double difference = fabs(left - right);
    const double magnitude = left > right ? left : right;

    return isfinite(left) && isfinite(right) &&
           difference <= 1e-5 * (magnitude > 1e-30 ? magnitude : 1e-30);
}

/* Compute the accumulator scale without allowing a float product to wrap to
 * infinity or underflow to zero.  Model scales have already been checked as
 * positive finite IEEE-754 single-precision values, so a double product is
 * sufficient for the full input range (at most FLT_MAX squared). */
static int checked_scale_product(float lhs, float rhs, float *product)
{
    const double value = (double)lhs * (double)rhs;

    if (product == NULL || !isfinite(value) || value <= 0.0 ||
        value > (double)FLT_MAX)
        return 0;
    *product = (float)value;
    return isfinite((double)*product) && *product > 0.0f;
}

static int multiplier_matches_scales(float input_scale, float weight_scale,
                                     float output_scale, int32_t multiplier,
                                     uint32_t shift)
{
    const double accumulator_scale = (double)input_scale *
                                     (double)weight_scale;
    const double real_multiplier = accumulator_scale / (double)output_scale;
    const long double scaled = ldexpl((long double)real_multiplier,
                                      (int)shift);
    const long double rounded = floorl(scaled + 0.5L);

    if (shift > 62U || multiplier <= 0 || !isfinite(accumulator_scale) ||
        !isfinite(real_multiplier) || !isfinite((double)scaled) ||
        real_multiplier <= 0.0 || rounded < 1.0L ||
        rounded > (long double)INT32_MAX)
        return 0;
    return rounded == (long double)multiplier;
}

static void decode_tensor_record(const uint8_t *record,
                                 tiny3tpu_tensor_view *tensor)
{
    tensor->id = read_u32(record, TINY3TPU_TENSOR_ID_OFFSET);
    tensor->dtype = record[TINY3TPU_TENSOR_META_OFFSET];
    tensor->rank = record[TINY3TPU_TENSOR_META_OFFSET + 1U];
    tensor->layout = record[TINY3TPU_TENSOR_META_OFFSET + 2U];
    tensor->flags = record[TINY3TPU_TENSOR_META_OFFSET + 3U];
    tensor->dims[0] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET);
    tensor->dims[1] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET + 4U);
    tensor->dims[2] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET + 8U);
    tensor->dims[3] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET + 12U);
    tensor->byte_offset = read_u32(record, TINY3TPU_TENSOR_BYTE_OFFSET);
    tensor->byte_size = read_u32(record, TINY3TPU_TENSOR_BYTE_SIZE_OFFSET);
    tensor->scale_bits = read_u32(record, TINY3TPU_TENSOR_SCALE_OFFSET);
    tensor->zero_point = (int32_t)read_u32(record, TINY3TPU_TENSOR_ZERO_POINT_OFFSET);
    tensor->reserved0 = read_u32(record, TINY3TPU_TENSOR_RESERVED0_OFFSET);
    tensor->reserved1 = read_u32(record, TINY3TPU_TENSOR_RESERVED1_OFFSET);
}

static int model_tensor_by_id(const uint8_t *model,
                              const tiny3tpu_model_header_view *header,
                              uint32_t tensor_id,
                              tiny3tpu_tensor_view *tensor)
{
    uint32_t index;

    if (tensor == NULL || !tensor_id_index(model, header, tensor_id, &index))
        return 0;
    decode_tensor_record(model + header->tensor_table_offset +
                         index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES, tensor);
    return 1;
}

static int qgemm_semantics_valid(const uint8_t *model,
                                 const tiny3tpu_model_header_view *header,
                                 const uint8_t *operation,
                                 const uint8_t *parameter)
{
    tiny3tpu_tensor_view activation;
    tiny3tpu_tensor_view weight;
    tiny3tpu_tensor_view bias;
    tiny3tpu_tensor_view output;
    float accumulator_scale;
    const int32_t multiplier = (int32_t)read_u32(parameter, 0U);
    const uint32_t shift = read_u32(parameter, 4U);
    const uint32_t flags = read_u32(parameter, 8U);
    const uint32_t activation_id = read_u32(
        operation, TINY3TPU_OPERATION_INPUTS_OFFSET);
    const uint32_t weight_id = read_u32(
        operation, TINY3TPU_OPERATION_INPUTS_OFFSET + 4U);
    const uint32_t bias_id = read_u32(
        operation, TINY3TPU_OPERATION_INPUTS_OFFSET + 8U);
    const uint32_t output_id = read_u32(
        operation, TINY3TPU_OPERATION_OUTPUTS_OFFSET);
    const int requantize = (flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0U;

    if (!model_tensor_by_id(model, header, activation_id, &activation) ||
        !model_tensor_by_id(model, header, weight_id, &weight) ||
        !model_tensor_by_id(model, header, bias_id, &bias) ||
        !model_tensor_by_id(model, header, output_id, &output))
        return 0;
    if ((activation.flags & TINY3TPU_TENSOR_CONSTANT) != 0U ||
        (activation.dtype != TINY3TPU_DTYPE_I8 &&
         activation.dtype != TINY3TPU_DTYPE_U8) ||
        activation.layout != TINY3TPU_LAYOUT_PACKED ||
        weight.dtype != TINY3TPU_DTYPE_I8 ||
        weight.flags != TINY3TPU_TENSOR_CONSTANT ||
        weight.layout != TINY3TPU_LAYOUT_PACKED || weight.rank != 2U ||
        bias.dtype != TINY3TPU_DTYPE_I32 ||
        bias.flags != TINY3TPU_TENSOR_CONSTANT ||
        bias.layout != TINY3TPU_LAYOUT_PACKED || bias.rank != 1U ||
        output.layout != TINY3TPU_LAYOUT_PACKED ||
        (output.flags & (TINY3TPU_TENSOR_INPUT |
                         TINY3TPU_TENSOR_CONSTANT |
                         TINY3TPU_TENSOR_SCRATCH)) != 0U)
        return 0;
    if (!checked_scale_product(scale_from_bits(activation.scale_bits),
                               scale_from_bits(weight.scale_bits),
                               &accumulator_scale))
        return 0;
    if (!scales_match(scale_from_bits(bias.scale_bits), accumulator_scale))
        return 0;

    if (requantize) {
        /* A requantized result is a quantized activation.  Accepting int32
         * here would make the wire contract disagree with execution. */
        if (output.dtype != TINY3TPU_DTYPE_I8 ||
            !multiplier_matches_scales(
                scale_from_bits(activation.scale_bits),
                scale_from_bits(weight.scale_bits),
                scale_from_bits(output.scale_bits), multiplier, shift))
            return 0;
    } else if (output.dtype != TINY3TPU_DTYPE_I32 || multiplier != 0 ||
               shift != 0U ||
               !scales_match(scale_from_bits(output.scale_bits),
                             accumulator_scale)) {
        return 0;
    }
    return (flags & TINY3TPU_QGEMM_FLAG_RELU) == 0U ||
           output.dtype == TINY3TPU_DTYPE_I8;
}

static int64_t round_shift_symmetric(int64_t value, uint32_t shift)
{
    uint64_t magnitude;
    uint64_t rounding;
    uint64_t rounded;

    if (shift == 0U) return value;
    magnitude = value < 0 ? (uint64_t)(-value) : (uint64_t)value;
    rounding = UINT64_C(1) << (shift - 1U);
    rounded = (magnitude + rounding) >> shift;
    return value < 0 ? -(int64_t)rounded : (int64_t)rounded;
}

static int operation_parameter_shape_valid(uint32_t opcode,
                                           const uint8_t *parameter,
                                           uint32_t parameter_bytes)
{
    uint32_t flags;

    if (parameter == NULL) return 0;
    switch (opcode) {
    case TINY3TPU_OP_QGEMM:
        if (parameter_bytes != TINY3TPU_QGEMM_PARAMETER_BYTES ||
            read_u32(parameter, 4U) > 62U || read_u32(parameter, 12U) != 0U)
            return 0;
        flags = read_u32(parameter, 8U);
        if ((flags & ~(TINY3TPU_QGEMM_FLAG_REQUANT |
                       TINY3TPU_QGEMM_FLAG_RELU |
                       TINY3TPU_QGEMM_FLAG_WEIGHT_OUT_IN)) != 0U)
            return 0;
        if ((flags & TINY3TPU_QGEMM_FLAG_REQUANT) == 0U &&
            (read_u32(parameter, 0U) != 0U || read_u32(parameter, 4U) != 0U))
            return 0;
        if ((flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0U &&
            (read_u32(parameter, 0U) == 0U ||
             (int32_t)read_u32(parameter, 0U) < 0))
            return 0;
        return 1;
    case TINY3TPU_OP_QCONV2D:
        if (parameter_bytes != TINY3TPU_QCONV2D_PARAMETER_BYTES ||
            read_u32(parameter, TINY3TPU_QCONV2D_STRIDE_H_OFFSET) == 0U ||
            read_u32(parameter, TINY3TPU_QCONV2D_STRIDE_W_OFFSET) == 0U ||
            read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_H_OFFSET) == 0U ||
            read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_W_OFFSET) == 0U ||
            read_u32(parameter, TINY3TPU_QCONV2D_GROUPS_OFFSET) != 1U ||
            read_u32(parameter, TINY3TPU_QCONV2D_RESERVED_OFFSET) != 0U ||
            read_u32(parameter, TINY3TPU_QCONV2D_SHIFT_OFFSET) > 62U)
            return 0;
        flags = read_u32(parameter, TINY3TPU_QCONV2D_FLAGS_OFFSET);
        if ((flags & ~(TINY3TPU_QGEMM_FLAG_REQUANT |
                       TINY3TPU_QGEMM_FLAG_RELU)) != 0U)
            return 0;
        if ((flags & TINY3TPU_QGEMM_FLAG_REQUANT) == 0U)
            return read_u32(parameter, TINY3TPU_QCONV2D_MULTIPLIER_OFFSET) == 0U &&
                   read_u32(parameter, TINY3TPU_QCONV2D_SHIFT_OFFSET) == 0U;
        return read_u32(parameter, TINY3TPU_QCONV2D_MULTIPLIER_OFFSET) != 0U &&
               (int32_t)read_u32(parameter,
                                  TINY3TPU_QCONV2D_MULTIPLIER_OFFSET) > 0;
    case TINY3TPU_OP_MAX_POOL_2D:
        return parameter_bytes == TINY3TPU_MAX_POOL2D_PARAMETER_BYTES &&
               read_u32(parameter, TINY3TPU_MAX_POOL2D_KERNEL_H_OFFSET) != 0U &&
               read_u32(parameter, TINY3TPU_MAX_POOL2D_KERNEL_W_OFFSET) != 0U &&
               read_u32(parameter, TINY3TPU_MAX_POOL2D_STRIDE_H_OFFSET) != 0U &&
               read_u32(parameter, TINY3TPU_MAX_POOL2D_STRIDE_W_OFFSET) != 0U &&
               read_u32(parameter, TINY3TPU_MAX_POOL2D_RESERVED_OFFSET) == 0U;
    case TINY3TPU_OP_RESHAPE: {
        const uint32_t rank = read_u32(parameter, 0U);
        uint32_t index;
        if (parameter_bytes != TINY3TPU_RESHAPE_PARAMETER_BYTES ||
            rank == 0U || rank > TINY3TPU_MAX_RANK ||
            read_u32(parameter, 20U) != 0U) return 0;
        for (index = 0U; index < TINY3TPU_MAX_RANK; ++index) {
            const uint32_t dimension = read_u32(parameter, 4U + index * 4U);
            if (index < rank) {
                if (dimension == 0U) return 0;
            } else if (dimension != 0U) return 0;
        }
        return 1;
    }
    case TINY3TPU_OP_ARGMAX:
        return parameter_bytes == TINY3TPU_ARGMAX_PARAMETER_BYTES &&
               read_u32(parameter, 0U) == 0U && read_u32(parameter, 4U) == 0U;
    default:
        return 0;
    }
}

static uint32_t crc32_model(const uint8_t *bytes, uint32_t length)
{
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    uint32_t index;

    for (index = 0U; index < length; ++index) {
        uint32_t value = bytes[index];
        uint32_t bit;

        if (index >= TINY3TPU_HEADER_CRC32_OFFSET &&
            index < TINY3TPU_HEADER_CRC32_OFFSET + sizeof(uint32_t)) {
            value = 0U;
        }
        crc ^= value;
        for (bit = 0U; bit < 8U; ++bit) {
            const uint32_t mask = (uint32_t)-(int32_t)(crc & 1U);
            crc = (crc >> 1U) ^ (UINT32_C(0xEDB88320) & mask);
        }
    }
    return ~crc;
}

static int runtime_is_ready(const tiny3tpu_runtime *runtime)
{
    return runtime != NULL && runtime->initialized != 0U &&
           runtime->model != NULL &&
           runtime->model_bytes >= TINY3TPU_MODEL_HEADER_BYTES &&
           runtime->parsed_model.bytes == runtime->model;
}

static void parse_header(const uint8_t *bytes, tiny3tpu_model_header_view *header)
{
    header->magic = read_u32(bytes, TINY3TPU_HEADER_MAGIC_OFFSET);
    header->version = read_u32(bytes, TINY3TPU_HEADER_VERSION_OFFSET);
    header->header_bytes = read_u32(bytes, TINY3TPU_HEADER_BYTES_OFFSET);
    header->total_bytes = read_u32(bytes, TINY3TPU_HEADER_TOTAL_BYTES_OFFSET);
    header->tensor_count = read_u32(bytes, TINY3TPU_HEADER_TENSOR_COUNT_OFFSET);
    header->operation_count = read_u32(bytes, TINY3TPU_HEADER_OPERATION_COUNT_OFFSET);
    header->tensor_table_offset = read_u32(bytes, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET);
    header->operation_table_offset = read_u32(bytes, TINY3TPU_HEADER_OPERATION_TABLE_OFFSET);
    header->parameter_offset = read_u32(bytes, TINY3TPU_HEADER_PARAMETER_OFFSET);
    header->parameter_bytes = read_u32(bytes, TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET);
    header->constant_offset = read_u32(bytes, TINY3TPU_HEADER_CONSTANT_OFFSET);
    header->constant_bytes = read_u32(bytes, TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET);
    header->arena_offset = read_u32(bytes, TINY3TPU_HEADER_ARENA_OFFSET);
    header->arena_bytes = read_u32(bytes, TINY3TPU_HEADER_ARENA_BYTES_OFFSET);
    header->scratch_offset = read_u32(bytes, TINY3TPU_HEADER_SCRATCH_OFFSET);
    header->scratch_bytes = read_u32(bytes, TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET);
    header->input_count = read_u32(bytes, TINY3TPU_HEADER_INPUT_COUNT_OFFSET);
    header->output_count = read_u32(bytes, TINY3TPU_HEADER_OUTPUT_COUNT_OFFSET);
    header->flags = read_u32(bytes, TINY3TPU_HEADER_FLAGS_OFFSET);
    header->crc32 = read_u32(bytes, TINY3TPU_HEADER_CRC32_OFFSET);
}

static tiny3tpu_runtime_status get_tensor_record(
    const tiny3tpu_runtime *runtime, uint32_t index,
    tiny3tpu_tensor_view *tensor)
{
    const uint8_t *record;

    if (runtime == NULL || tensor == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (!runtime_is_ready(runtime)) return TINY3TPU_RUNTIME_NOT_READY;
    if (index >= runtime->parsed_model.header.tensor_count)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;

    record = runtime->parsed_model.tensor_table +
             index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
    tensor->id = read_u32(record, TINY3TPU_TENSOR_ID_OFFSET);
    tensor->dtype = record[TINY3TPU_TENSOR_META_OFFSET];
    tensor->rank = record[TINY3TPU_TENSOR_META_OFFSET + 1U];
    tensor->layout = record[TINY3TPU_TENSOR_META_OFFSET + 2U];
    tensor->flags = record[TINY3TPU_TENSOR_META_OFFSET + 3U];
    tensor->dims[0] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET);
    tensor->dims[1] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET + 4U);
    tensor->dims[2] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET + 8U);
    tensor->dims[3] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET + 12U);
    tensor->byte_offset = read_u32(record, TINY3TPU_TENSOR_BYTE_OFFSET);
    tensor->byte_size = read_u32(record, TINY3TPU_TENSOR_BYTE_SIZE_OFFSET);
    tensor->scale_bits = read_u32(record, TINY3TPU_TENSOR_SCALE_OFFSET);
    tensor->zero_point = (int32_t)read_u32(record, TINY3TPU_TENSOR_ZERO_POINT_OFFSET);
    tensor->reserved0 = read_u32(record, TINY3TPU_TENSOR_RESERVED0_OFFSET);
    tensor->reserved1 = read_u32(record, TINY3TPU_TENSOR_RESERVED1_OFFSET);
    return TINY3TPU_RUNTIME_OK;
}

static tiny3tpu_runtime_status get_operation_record(
    const tiny3tpu_runtime *runtime, uint32_t index,
    tiny3tpu_operation_view *operation)
{
    const uint8_t *record;

    if (runtime == NULL || operation == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (!runtime_is_ready(runtime)) return TINY3TPU_RUNTIME_NOT_READY;
    if (index >= runtime->parsed_model.header.operation_count)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;

    record = runtime->parsed_model.operation_table +
             index * TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
    operation->opcode = read_u32(record, TINY3TPU_OPERATION_OPCODE_OFFSET);
    operation->version = read_u32(record, TINY3TPU_OPERATION_VERSION_OFFSET);
    operation->inputs[0] = read_u32(record, TINY3TPU_OPERATION_INPUTS_OFFSET);
    operation->inputs[1] = read_u32(record, TINY3TPU_OPERATION_INPUTS_OFFSET + 4U);
    operation->inputs[2] = read_u32(record, TINY3TPU_OPERATION_INPUTS_OFFSET + 8U);
    operation->outputs[0] = read_u32(record, TINY3TPU_OPERATION_OUTPUTS_OFFSET);
    operation->outputs[1] = read_u32(record, TINY3TPU_OPERATION_OUTPUTS_OFFSET + 4U);
    operation->parameter_offset = read_u32(record, TINY3TPU_OPERATION_PARAMETER_OFFSET);
    operation->parameter_bytes = read_u32(record, TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET);
    operation->reserved = read_u32(record, TINY3TPU_OPERATION_RESERVED_OFFSET);
    return TINY3TPU_RUNTIME_OK;
}

static tiny3tpu_runtime_status find_tensor_by_id(
    const tiny3tpu_runtime *runtime, uint32_t tensor_id,
    tiny3tpu_tensor_view *tensor)
{
    uint32_t index;

    if (runtime == NULL || tensor == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    for (index = 0U; index < runtime->parsed_model.header.tensor_count; ++index) {
        tiny3tpu_runtime_status status = get_tensor_record(runtime, index, tensor);
        if (status != TINY3TPU_RUNTIME_OK) return status;
        if (tensor->id == tensor_id) return TINY3TPU_RUNTIME_OK;
    }
    return TINY3TPU_RUNTIME_BAD_ARGUMENT;
}

static tiny3tpu_runtime_status activation_pointer(
    const tiny3tpu_runtime *runtime, const tiny3tpu_tensor_view *tensor,
    uint8_t **pointer)
{
    uint32_t relative_offset;

    if (runtime == NULL || tensor == NULL || pointer == NULL)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->activation_storage == NULL ||
        tensor->byte_offset < runtime->parsed_model.header.arena_offset)
        return TINY3TPU_RUNTIME_NO_MEMORY;
    relative_offset = tensor->byte_offset - runtime->parsed_model.header.arena_offset;
    if (!range_is_inside(relative_offset, tensor->byte_size,
                         runtime->activation_storage_bytes))
        return TINY3TPU_RUNTIME_NO_MEMORY;
    *pointer = runtime->activation_storage + relative_offset;
    return TINY3TPU_RUNTIME_OK;
}

/* Return the bytes for either a model constant or a live activation.  The
 * caller owns the workspace; constants remain borrowed from the model. */
static tiny3tpu_runtime_status tensor_data_pointer(
    const tiny3tpu_runtime *runtime, const tiny3tpu_tensor_view *tensor,
    const uint8_t **pointer)
{
    uint8_t *activation;

    if (runtime == NULL || tensor == NULL || pointer == NULL)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if ((tensor->flags & TINY3TPU_TENSOR_CONSTANT) != 0U) {
        if (tensor->byte_offset > runtime->model_bytes ||
            tensor->byte_size > runtime->model_bytes - tensor->byte_offset)
            return TINY3TPU_RUNTIME_BAD_MODEL;
        *pointer = runtime->model + tensor->byte_offset;
        return TINY3TPU_RUNTIME_OK;
    }
    if (activation_pointer(runtime, tensor, &activation) !=
        TINY3TPU_RUNTIME_OK)
        return TINY3TPU_RUNTIME_NO_MEMORY;
    *pointer = activation;
    return TINY3TPU_RUNTIME_OK;
}

static int32_t read_i32(const uint8_t *bytes)
{
    return (int32_t)(((uint32_t)bytes[0]) |
                      ((uint32_t)bytes[1] << 8U) |
                      ((uint32_t)bytes[2] << 16U) |
                      ((uint32_t)bytes[3] << 24U));
}

static void write_i32(uint8_t *bytes, int32_t value)
{
    const uint32_t bits = (uint32_t)value;
    bytes[0] = (uint8_t)bits;
    bytes[1] = (uint8_t)(bits >> 8U);
    bytes[2] = (uint8_t)(bits >> 16U);
    bytes[3] = (uint8_t)(bits >> 24U);
}

static int products_fit_u32(uint32_t left, uint32_t right,
                            uint32_t factor, uint32_t *product)
{
    const uint64_t value = (uint64_t)left * right * factor;
    if (product == NULL || value > UINT32_MAX) return 0;
    *product = (uint32_t)value;
    return 1;
}

static int spatial_output_dimension(uint32_t input, uint32_t pad_before,
                                    uint32_t pad_after, uint32_t kernel,
                                    uint32_t stride, uint32_t *output)
{
    const uint64_t padded = (uint64_t)input + pad_before + pad_after;
    uint64_t result;

    if (output == NULL || kernel == 0U || stride == 0U || padded < kernel)
        return 0;
    result = (padded - kernel) / stride + 1U;
    if (result > UINT32_MAX) return 0;
    *output = (uint32_t)result;
    return 1;
}

static int qconv2d_semantics_valid(
    const uint8_t *model, const tiny3tpu_model_header_view *header,
    const uint8_t *operation, const uint8_t *parameter)
{
    tiny3tpu_tensor_view input;
    tiny3tpu_tensor_view weight;
    tiny3tpu_tensor_view bias;
    tiny3tpu_tensor_view output;
    uint32_t output_height;
    uint32_t output_width;
    uint32_t input_bytes;
    uint32_t weight_bytes;
    uint32_t bias_bytes;
    uint32_t output_bytes;
    float accumulator_scale;
    const uint32_t flags = read_u32(
        parameter, TINY3TPU_QCONV2D_FLAGS_OFFSET);
    const int requantize = (flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0U;

    if (!model_tensor_by_id(
            model, header,
            read_u32(operation, TINY3TPU_OPERATION_INPUTS_OFFSET), &input) ||
        !model_tensor_by_id(
            model, header,
            read_u32(operation, TINY3TPU_OPERATION_INPUTS_OFFSET + 4U),
            &weight) ||
        !model_tensor_by_id(
            model, header,
            read_u32(operation, TINY3TPU_OPERATION_INPUTS_OFFSET + 8U),
            &bias) ||
        !model_tensor_by_id(
            model, header,
            read_u32(operation, TINY3TPU_OPERATION_OUTPUTS_OFFSET), &output))
        return 0;
    if ((input.flags & TINY3TPU_TENSOR_CONSTANT) != 0U ||
        input.dtype != TINY3TPU_DTYPE_I8 ||
        input.layout != TINY3TPU_LAYOUT_NHWC || input.rank != 4U ||
        weight.dtype != TINY3TPU_DTYPE_I8 ||
        weight.flags != TINY3TPU_TENSOR_CONSTANT ||
        weight.layout != TINY3TPU_LAYOUT_PACKED || weight.rank != 4U ||
        bias.dtype != TINY3TPU_DTYPE_I32 ||
        bias.flags != TINY3TPU_TENSOR_CONSTANT ||
        bias.layout != TINY3TPU_LAYOUT_PACKED || bias.rank != 1U ||
        output.layout != TINY3TPU_LAYOUT_NHWC || output.rank != 4U ||
        (output.flags & (TINY3TPU_TENSOR_INPUT |
                         TINY3TPU_TENSOR_CONSTANT |
                         TINY3TPU_TENSOR_SCRATCH)) != 0U ||
        read_u32(parameter, TINY3TPU_QCONV2D_GROUPS_OFFSET) != 1U ||
        (flags & ~(
            TINY3TPU_QGEMM_FLAG_REQUANT | TINY3TPU_QGEMM_FLAG_RELU)) != 0U)
        return 0;
    if (!spatial_output_dimension(
            input.dims[1], read_u32(parameter, TINY3TPU_QCONV2D_PAD_TOP_OFFSET),
            read_u32(parameter, TINY3TPU_QCONV2D_PAD_BOTTOM_OFFSET),
            read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_H_OFFSET),
            read_u32(parameter, TINY3TPU_QCONV2D_STRIDE_H_OFFSET),
            &output_height) ||
        !spatial_output_dimension(
            input.dims[2], read_u32(parameter, TINY3TPU_QCONV2D_PAD_LEFT_OFFSET),
            read_u32(parameter, TINY3TPU_QCONV2D_PAD_RIGHT_OFFSET),
            read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_W_OFFSET),
            read_u32(parameter, TINY3TPU_QCONV2D_STRIDE_W_OFFSET),
            &output_width) ||
        weight.dims[0] != read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_H_OFFSET) ||
        weight.dims[1] != read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_W_OFFSET) ||
        weight.dims[2] != input.dims[3] ||
        bias.dims[0] != weight.dims[3] || output.dims[0] != input.dims[0] ||
        output.dims[1] != output_height || output.dims[2] != output_width ||
        output.dims[3] != weight.dims[3] ||
        !tensor_byte_size(input.dtype, input.dims, input.rank, &input_bytes) ||
        !tensor_byte_size(weight.dtype, weight.dims, weight.rank, &weight_bytes) ||
        !tensor_byte_size(bias.dtype, bias.dims, bias.rank, &bias_bytes) ||
        !tensor_byte_size(output.dtype, output.dims, output.rank, &output_bytes) ||
        input.byte_size != input_bytes || weight.byte_size != weight_bytes ||
        bias.byte_size != bias_bytes || output.byte_size != output_bytes ||
        !checked_scale_product(scale_from_bits(input.scale_bits),
                               scale_from_bits(weight.scale_bits),
                               &accumulator_scale) ||
        !scales_match(scale_from_bits(bias.scale_bits), accumulator_scale))
        return 0;
    if (requantize) {
        if (output.dtype != TINY3TPU_DTYPE_I8 ||
            !multiplier_matches_scales(
                scale_from_bits(input.scale_bits),
                scale_from_bits(weight.scale_bits),
                scale_from_bits(output.scale_bits),
                (int32_t)read_u32(
                    parameter, TINY3TPU_QCONV2D_MULTIPLIER_OFFSET),
                read_u32(parameter, TINY3TPU_QCONV2D_SHIFT_OFFSET)))
            return 0;
    } else if (output.dtype != TINY3TPU_DTYPE_I32 ||
               read_u32(parameter, TINY3TPU_QCONV2D_MULTIPLIER_OFFSET) != 0U ||
               read_u32(parameter, TINY3TPU_QCONV2D_SHIFT_OFFSET) != 0U ||
               !scales_match(scale_from_bits(output.scale_bits),
                             accumulator_scale)) {
        return 0;
    }
    return (flags & TINY3TPU_QGEMM_FLAG_RELU) == 0U ||
           output.dtype == TINY3TPU_DTYPE_I8;
}

static int max_pool2d_semantics_valid(
    const uint8_t *model, const tiny3tpu_model_header_view *header,
    const uint8_t *operation, const uint8_t *parameter)
{
    tiny3tpu_tensor_view input;
    tiny3tpu_tensor_view output;
    uint32_t output_height;
    uint32_t output_width;
    uint32_t input_bytes;
    uint32_t output_bytes;

    if (!model_tensor_by_id(
            model, header,
            read_u32(operation, TINY3TPU_OPERATION_INPUTS_OFFSET), &input) ||
        !model_tensor_by_id(
            model, header,
            read_u32(operation, TINY3TPU_OPERATION_OUTPUTS_OFFSET), &output))
        return 0;
    if ((input.flags & TINY3TPU_TENSOR_CONSTANT) != 0U ||
        input.dtype != TINY3TPU_DTYPE_I8 ||
        input.layout != TINY3TPU_LAYOUT_NHWC || input.rank != 4U ||
        output.dtype != TINY3TPU_DTYPE_I8 ||
        output.layout != TINY3TPU_LAYOUT_NHWC || output.rank != 4U ||
        (output.flags & (TINY3TPU_TENSOR_INPUT |
                         TINY3TPU_TENSOR_CONSTANT |
                         TINY3TPU_TENSOR_SCRATCH)) != 0U ||
        !spatial_output_dimension(
            input.dims[1],
            read_u32(parameter, TINY3TPU_MAX_POOL2D_PAD_TOP_OFFSET),
            read_u32(parameter, TINY3TPU_MAX_POOL2D_PAD_BOTTOM_OFFSET),
            read_u32(parameter, TINY3TPU_MAX_POOL2D_KERNEL_H_OFFSET),
            read_u32(parameter, TINY3TPU_MAX_POOL2D_STRIDE_H_OFFSET),
            &output_height) ||
        !spatial_output_dimension(
            input.dims[2],
            read_u32(parameter, TINY3TPU_MAX_POOL2D_PAD_LEFT_OFFSET),
            read_u32(parameter, TINY3TPU_MAX_POOL2D_PAD_RIGHT_OFFSET),
            read_u32(parameter, TINY3TPU_MAX_POOL2D_KERNEL_W_OFFSET),
            read_u32(parameter, TINY3TPU_MAX_POOL2D_STRIDE_W_OFFSET),
            &output_width) ||
        output.dims[0] != input.dims[0] || output.dims[1] != output_height ||
        output.dims[2] != output_width || output.dims[3] != input.dims[3] ||
        input.scale_bits != output.scale_bits || input.zero_point != 0 ||
        output.zero_point != 0 ||
        !tensor_byte_size(input.dtype, input.dims, input.rank, &input_bytes) ||
        !tensor_byte_size(output.dtype, output.dims, output.rank, &output_bytes) ||
        input.byte_size != input_bytes || output.byte_size != output_bytes)
        return 0;
    return 1;
}

static tiny3tpu_runtime_status execute_qgemm(
    tiny3tpu_runtime *runtime, const tiny3tpu_operation_view *operation)
{
    tiny3tpu_tensor_view activation;
    tiny3tpu_tensor_view weight;
    tiny3tpu_tensor_view bias;
    tiny3tpu_tensor_view output;
    const uint8_t *parameter;
    uint8_t *activation_bytes;
    uint8_t *output_bytes;
    const uint8_t *weight_bytes;
    const uint8_t *bias_bytes;
    uint32_t m;
    uint32_t k;
    uint32_t n;
    uint32_t row;
    uint32_t column;
    uint32_t inner;
    uint32_t activation_bytes_expected;
    uint32_t weight_bytes_expected;
    uint32_t bias_bytes_expected;
    uint32_t output_bytes_expected;
    int32_t multiplier;
    uint32_t shift;
    uint32_t qgemm_flags;
    uint32_t output_element_bytes;
    tiny3tpu_runtime_status status;

    status = find_tensor_by_id(runtime, operation->inputs[0], &activation);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->inputs[1], &weight);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->inputs[2], &bias);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->outputs[0], &output);
    if (status != TINY3TPU_RUNTIME_OK) return status;

    if (operation->parameter_bytes != TINY3TPU_QGEMM_PARAMETER_BYTES)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    parameter = runtime->model + operation->parameter_offset;
    multiplier = (int32_t)read_u32(parameter, 0U);
    shift = read_u32(parameter, 4U);
    qgemm_flags = read_u32(parameter, 8U);
    if (read_u32(parameter, 12U) != 0U || shift > 62U ||
        (qgemm_flags & ~(TINY3TPU_QGEMM_FLAG_REQUANT |
                         TINY3TPU_QGEMM_FLAG_RELU |
                         TINY3TPU_QGEMM_FLAG_WEIGHT_OUT_IN)) != 0U ||
        ((qgemm_flags & TINY3TPU_QGEMM_FLAG_REQUANT) == 0U &&
         (multiplier != 0 || shift != 0U)) ||
        ((qgemm_flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0U && multiplier <= 0))
        return TINY3TPU_RUNTIME_BAD_MODEL;
    if ((activation.flags & TINY3TPU_TENSOR_CONSTANT) != 0U ||
        (activation.dtype != TINY3TPU_DTYPE_I8 &&
         activation.dtype != TINY3TPU_DTYPE_U8) ||
        activation.layout != TINY3TPU_LAYOUT_PACKED ||
        weight.dtype != TINY3TPU_DTYPE_I8 ||
        weight.flags != TINY3TPU_TENSOR_CONSTANT ||
        weight.layout != TINY3TPU_LAYOUT_PACKED || weight.rank != 2U ||
        bias.dtype != TINY3TPU_DTYPE_I32 ||
        bias.flags != TINY3TPU_TENSOR_CONSTANT ||
        bias.layout != TINY3TPU_LAYOUT_PACKED || bias.rank != 1U ||
        output.layout != TINY3TPU_LAYOUT_PACKED ||
        (output.flags & (TINY3TPU_TENSOR_INPUT |
                         TINY3TPU_TENSOR_CONSTANT |
                         TINY3TPU_TENSOR_SCRATCH)) != 0U)
        return TINY3TPU_RUNTIME_UNSUPPORTED;
    if ((qgemm_flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0U) {
        if (output.dtype != TINY3TPU_DTYPE_I8) return TINY3TPU_RUNTIME_BAD_MODEL;
        output_element_bytes = 1U;
    } else {
        if (output.dtype != TINY3TPU_DTYPE_I32) return TINY3TPU_RUNTIME_BAD_MODEL;
        output_element_bytes = (uint32_t)sizeof(int32_t);
    }
    if (activation.rank == 1U) {
        m = 1U;
        k = activation.dims[0];
        if (output.rank != 1U) return TINY3TPU_RUNTIME_BAD_MODEL;
    } else if (activation.rank == 2U) {
        m = activation.dims[0];
        k = activation.dims[1];
        if (output.rank != 2U) return TINY3TPU_RUNTIME_BAD_MODEL;
    } else {
        return TINY3TPU_RUNTIME_UNSUPPORTED;
    }
    n = weight.dims[0];
    if (!products_fit_u32(m, k, 1U, &activation_bytes_expected) ||
        !products_fit_u32(n, k, 1U, &weight_bytes_expected) ||
        !products_fit_u32(n, 1U, (uint32_t)sizeof(int32_t),
                          &bias_bytes_expected) ||
        !products_fit_u32(m, n, output_element_bytes,
                          &output_bytes_expected) ||
        weight.dims[1] != k || bias.dims[0] != n ||
        (activation.rank == 1U ? output.dims[0] != n :
         (output.dims[0] != m || output.dims[1] != n)) ||
        activation.byte_size != activation_bytes_expected ||
        weight.byte_size != weight_bytes_expected ||
        bias.byte_size != bias_bytes_expected ||
        output.byte_size != output_bytes_expected)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    status = activation_pointer(runtime, &activation, &activation_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = activation_pointer(runtime, &output, &output_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    weight_bytes = runtime->model + weight.byte_offset;
    bias_bytes = runtime->model + bias.byte_offset;
    /* The callback ABI is signed int8.  Keep U8 activations on the portable
     * path until a backend explicitly advertises an unsigned input mode. */
    if ((qgemm_flags & TINY3TPU_QGEMM_FLAG_REQUANT) == 0U &&
        runtime->backend != NULL && runtime->backend->run != NULL &&
        activation.dtype == TINY3TPU_DTYPE_I8 &&
        (uintptr_t)output_bytes % _Alignof(int32_t) == 0U) {
        uint8_t *packed_weights;
        uint32_t weight_row;
        uint32_t weight_column;
        if (!range_is_inside(runtime->parsed_model.header.arena_bytes,
                             weight.byte_size,
                             runtime->activation_storage_bytes))
            return TINY3TPU_RUNTIME_NO_MEMORY;
        packed_weights = runtime->activation_storage +
                         runtime->parsed_model.header.arena_bytes;
        for (weight_row = 0U; weight_row < k; ++weight_row)
            for (weight_column = 0U; weight_column < n; ++weight_column)
                packed_weights[weight_row * n + weight_column] =
                    weight_bytes[weight_column * k + weight_row];
        if (runtime->backend->run(runtime->backend->user,
                                  (const int8_t *)activation_bytes,
                                  (const int8_t *)packed_weights,
                                  (int32_t *)output_bytes,
                                  m, k, n) != 0)
            return TINY3TPU_RUNTIME_BACKEND_ERROR;
        for (row = 0U; row < m; ++row) {
            for (column = 0U; column < n; ++column) {
                int64_t sum = (int64_t)read_i32(bias_bytes + column * 4U) +
                              (int64_t)read_i32(output_bytes +
                                                 (row * n + column) * 4U);
                if (sum < INT32_MIN || sum > INT32_MAX)
                    return TINY3TPU_RUNTIME_BACKEND_ERROR;
                write_i32(output_bytes + (row * n + column) * 4U, (int32_t)sum);
            }
        }
        return TINY3TPU_RUNTIME_OK;
    }
    for (row = 0U; row < m; ++row) {
        for (column = 0U; column < n; ++column) {
            int64_t sum = (int64_t)read_i32(bias_bytes + column * 4U);
            for (inner = 0U; inner < k; ++inner) {
                int32_t lhs = activation.dtype == TINY3TPU_DTYPE_U8
                                  ? (int32_t)activation_bytes[row * k + inner]
                                  : (int32_t)((const int8_t *)activation_bytes)[row * k + inner];
                const int32_t rhs = (int32_t)((const int8_t *)weight_bytes)[column * k + inner];
                sum += (int64_t)lhs * rhs;
            }
            if (sum < INT32_MIN || sum > INT32_MAX)
                return TINY3TPU_RUNTIME_BACKEND_ERROR;
            if ((qgemm_flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0U) {
                int64_t product = sum * (int64_t)multiplier;
                int64_t quantized;
                quantized = round_shift_symmetric(product, shift);
                if ((qgemm_flags & TINY3TPU_QGEMM_FLAG_RELU) != 0U && quantized < 0)
                    quantized = 0;
                if (quantized > 127) quantized = 127;
                if (quantized < -128) quantized = -128;
                output_bytes[row * n + column] = (uint8_t)(int8_t)quantized;
            } else {
                write_i32(output_bytes + (row * n + column) * 4U, (int32_t)sum);
            }
        }
    }
    return TINY3TPU_RUNTIME_OK;
}

static tiny3tpu_runtime_status execute_qconv2d(
    tiny3tpu_runtime *runtime, const tiny3tpu_operation_view *operation)
{
    tiny3tpu_tensor_view input, weight, bias, output;
    const uint8_t *parameter, *input_bytes, *weight_bytes, *bias_bytes;
    uint8_t *output_bytes;
    uint32_t batch, oh, ow, oc, kh, kw, ic;
    uint32_t input_h, input_w, input_c, output_h, output_w, output_c;
    uint32_t stride_h, stride_w, pad_top, pad_left, kernel_h, kernel_w;
    uint32_t flags, shift;
    int32_t multiplier;
    tiny3tpu_runtime_status status;

    status = find_tensor_by_id(runtime, operation->inputs[0], &input);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->inputs[1], &weight);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->inputs[2], &bias);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->outputs[0], &output);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    parameter = runtime->model + operation->parameter_offset;
    if (operation->parameter_bytes != TINY3TPU_QCONV2D_PARAMETER_BYTES ||
        input.rank != 4U || weight.rank != 4U || bias.rank != 1U || output.rank != 4U ||
        input.layout != TINY3TPU_LAYOUT_NHWC || weight.layout != TINY3TPU_LAYOUT_PACKED ||
        output.layout != TINY3TPU_LAYOUT_NHWC || input.dtype != TINY3TPU_DTYPE_I8 ||
        weight.dtype != TINY3TPU_DTYPE_I8 || bias.dtype != TINY3TPU_DTYPE_I32 ||
        (output.dtype != TINY3TPU_DTYPE_I32 && output.dtype != TINY3TPU_DTYPE_I8))
        return TINY3TPU_RUNTIME_BAD_MODEL;
    stride_h = read_u32(parameter, TINY3TPU_QCONV2D_STRIDE_H_OFFSET);
    stride_w = read_u32(parameter, TINY3TPU_QCONV2D_STRIDE_W_OFFSET);
    pad_top = read_u32(parameter, TINY3TPU_QCONV2D_PAD_TOP_OFFSET);
    pad_left = read_u32(parameter, TINY3TPU_QCONV2D_PAD_LEFT_OFFSET);
    kernel_h = read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_H_OFFSET);
    kernel_w = read_u32(parameter, TINY3TPU_QCONV2D_KERNEL_W_OFFSET);
    flags = read_u32(parameter, TINY3TPU_QCONV2D_FLAGS_OFFSET);
    multiplier = (int32_t)read_u32(parameter, TINY3TPU_QCONV2D_MULTIPLIER_OFFSET);
    shift = read_u32(parameter, TINY3TPU_QCONV2D_SHIFT_OFFSET);
    input_h = input.dims[1]; input_w = input.dims[2]; input_c = input.dims[3];
    output_h = output.dims[1]; output_w = output.dims[2]; output_c = output.dims[3];
    if (weight.dims[0] != kernel_h || weight.dims[1] != kernel_w ||
        weight.dims[2] != input_c || weight.dims[3] != output_c || bias.dims[0] != output_c)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    status = tensor_data_pointer(runtime, &input, &input_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = tensor_data_pointer(runtime, &weight, &weight_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = tensor_data_pointer(runtime, &bias, &bias_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = activation_pointer(runtime, &output, &output_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    for (batch = 0U; batch < input.dims[0]; ++batch)
    for (oh = 0U; oh < output_h; ++oh) for (ow = 0U; ow < output_w; ++ow) {
        for (oc = 0U; oc < output_c; ++oc) {
            int64_t sum = read_i32(bias_bytes + oc * 4U);
            for (kh = 0U; kh < kernel_h; ++kh) for (kw = 0U; kw < kernel_w; ++kw) {
                const int64_t y = (int64_t)oh * stride_h + kh - pad_top;
                const int64_t x = (int64_t)ow * stride_w + kw - pad_left;
                if (y < 0 || x < 0 || y >= (int64_t)input_h || x >= (int64_t)input_w) continue;
                for (ic = 0U; ic < input_c; ++ic) {
                    const uint32_t ai = (((batch * input_h + (uint32_t)y) * input_w + (uint32_t)x) * input_c) + ic;
                    const uint32_t wi = (((kh * kernel_w + kw) * input_c + ic) * output_c) + oc;
                    sum += (int64_t)((const int8_t *)input_bytes)[ai] *
                           (int64_t)((const int8_t *)weight_bytes)[wi];
                }
            }
            if (sum < INT32_MIN || sum > INT32_MAX) return TINY3TPU_RUNTIME_BACKEND_ERROR;
            if ((flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0U) {
                int64_t q = round_shift_symmetric(sum * multiplier, shift);
                if ((flags & TINY3TPU_QGEMM_FLAG_RELU) != 0U && q < 0) q = 0;
                if (q > 127) q = 127; if (q < -128) q = -128;
                output_bytes[((batch * output_h + oh) * output_w + ow) * output_c + oc] = (uint8_t)(int8_t)q;
            } else {
                write_i32(output_bytes + (((batch * output_h + oh) * output_w + ow) * output_c + oc) * 4U,
                          (int32_t)sum);
            }
        }
    }
    return TINY3TPU_RUNTIME_OK;
}

static tiny3tpu_runtime_status execute_max_pool2d(
    tiny3tpu_runtime *runtime, const tiny3tpu_operation_view *operation)
{
    tiny3tpu_tensor_view input, output;
    const uint8_t *parameter, *input_bytes;
    uint8_t *output_bytes;
    uint32_t batch, oh, ow, c, kh, kw;
    const uint32_t stride_h_offset = TINY3TPU_MAX_POOL2D_STRIDE_H_OFFSET;
    tiny3tpu_runtime_status status;
    status = find_tensor_by_id(runtime, operation->inputs[0], &input);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->outputs[0], &output);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    parameter = runtime->model + operation->parameter_offset;
    if (operation->parameter_bytes != TINY3TPU_MAX_POOL2D_PARAMETER_BYTES ||
        input.rank != 4U || output.rank != 4U || input.dtype != TINY3TPU_DTYPE_I8 ||
        output.dtype != TINY3TPU_DTYPE_I8 || input.layout != TINY3TPU_LAYOUT_NHWC ||
        output.layout != TINY3TPU_LAYOUT_NHWC || input.zero_point != 0 ||
        output.zero_point != 0 || input.scale_bits != output.scale_bits)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    status = tensor_data_pointer(runtime, &input, &input_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = activation_pointer(runtime, &output, &output_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    for (batch = 0U; batch < input.dims[0]; ++batch)
    for (oh = 0U; oh < output.dims[1]; ++oh) for (ow = 0U; ow < output.dims[2]; ++ow)
        for (c = 0U; c < output.dims[3]; ++c) {
            int32_t best = -128;
            for (kh = 0U; kh < read_u32(parameter, TINY3TPU_MAX_POOL2D_KERNEL_H_OFFSET); ++kh)
                for (kw = 0U; kw < read_u32(parameter, TINY3TPU_MAX_POOL2D_KERNEL_W_OFFSET); ++kw) {
                    const int64_t y = (int64_t)oh * read_u32(parameter, stride_h_offset) + kh -
                                      read_u32(parameter, TINY3TPU_MAX_POOL2D_PAD_TOP_OFFSET);
                    const int64_t x = (int64_t)ow * read_u32(parameter, TINY3TPU_MAX_POOL2D_STRIDE_W_OFFSET) + kw -
                                      read_u32(parameter, TINY3TPU_MAX_POOL2D_PAD_LEFT_OFFSET);
                    if (y >= 0 && x >= 0 && y < (int64_t)input.dims[1] && x < (int64_t)input.dims[2]) {
                        const uint32_t index = (((batch * input.dims[1] + (uint32_t)y) * input.dims[2] + (uint32_t)x) * input.dims[3]) + c;
                        const int32_t value = ((const int8_t *)input_bytes)[index];
                        if (value > best) best = value;
                    }
                }
            output_bytes[((batch * output.dims[1] + oh) * output.dims[2] + ow) * output.dims[3] + c] = (uint8_t)(int8_t)best;
        }
    return TINY3TPU_RUNTIME_OK;
}

static tiny3tpu_runtime_status execute_reshape(
    tiny3tpu_runtime *runtime, const tiny3tpu_operation_view *operation)
{
    tiny3tpu_tensor_view source;
    tiny3tpu_tensor_view destination;
    const uint8_t *source_bytes;
    uint8_t *destination_bytes;
    const uint8_t *parameter;
    uint32_t rank;
    uint32_t index;
    uint32_t source_bytes_expected;
    uint32_t destination_bytes_expected;
    uint64_t source_elements = 1U;
    uint64_t reshape_elements = 1U;
    tiny3tpu_runtime_status status;

    status = find_tensor_by_id(runtime, operation->inputs[0], &source);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->outputs[0], &destination);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    if (operation->parameter_bytes != TINY3TPU_RESHAPE_PARAMETER_BYTES)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    parameter = runtime->model + operation->parameter_offset;
    rank = read_u32(parameter, 0U);
    if (rank == 0U || rank > TINY3TPU_MAX_RANK ||
        read_u32(parameter, 20U) != 0U)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    if (source.layout != TINY3TPU_LAYOUT_PACKED ||
        destination.layout != TINY3TPU_LAYOUT_PACKED)
        return TINY3TPU_RUNTIME_UNSUPPORTED;
    if (source.dtype != destination.dtype ||
        source.scale_bits != destination.scale_bits ||
        source.zero_point != destination.zero_point ||
        destination.rank != rank)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    for (index = 0U; index < source.rank; ++index) {
        if (source.dims[index] == 0U) return TINY3TPU_RUNTIME_BAD_MODEL;
        source_elements *= source.dims[index];
        if (source_elements > UINT32_MAX) return TINY3TPU_RUNTIME_BAD_MODEL;
    }
    for (index = 0U; index < TINY3TPU_MAX_RANK; ++index) {
        const uint32_t dimension = read_u32(parameter, 4U + index * 4U);
        if (index < rank) {
            if (dimension == 0U) return TINY3TPU_RUNTIME_BAD_MODEL;
            if (destination.dims[index] != dimension)
                return TINY3TPU_RUNTIME_BAD_MODEL;
            reshape_elements *= dimension;
            if (reshape_elements > UINT32_MAX)
                return TINY3TPU_RUNTIME_BAD_MODEL;
        } else if (dimension != 0U || destination.dims[index] != 0U) {
            return TINY3TPU_RUNTIME_BAD_MODEL;
        }
    }
    if (source_elements != reshape_elements ||
        !tensor_byte_size(source.dtype, source.dims, source.rank,
                          &source_bytes_expected) ||
        !tensor_byte_size(destination.dtype, destination.dims,
                          destination.rank, &destination_bytes_expected) ||
        source.byte_size != source_bytes_expected ||
        destination.byte_size != destination_bytes_expected ||
        source.byte_size != destination.byte_size)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    status = tensor_data_pointer(runtime, &source, &source_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = activation_pointer(runtime, &destination, &destination_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    memmove(destination_bytes, source_bytes, source.byte_size);
    return TINY3TPU_RUNTIME_OK;
}

static int32_t read_element_as_i32(const uint8_t *bytes, uint8_t dtype,
                                   uint32_t index)
{
    if (dtype == TINY3TPU_DTYPE_I8)
        return (int32_t)((const int8_t *)bytes)[index];
    if (dtype == TINY3TPU_DTYPE_U8)
        return (int32_t)bytes[index];
    return read_i32(bytes + index * sizeof(int32_t));
}

static tiny3tpu_runtime_status execute_argmax(
    tiny3tpu_runtime *runtime, const tiny3tpu_operation_view *operation)
{
    tiny3tpu_tensor_view source;
    tiny3tpu_tensor_view destination;
    const uint8_t *source_bytes;
    uint8_t *destination_bytes;
    const uint8_t *parameter;
    uint32_t element_count;
    uint32_t index;
    uint32_t source_bytes_expected;
    int32_t best_value;
    uint32_t best_index = 0U;
    tiny3tpu_runtime_status status;

    status = find_tensor_by_id(runtime, operation->inputs[0], &source);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = find_tensor_by_id(runtime, operation->outputs[0], &destination);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    if (operation->parameter_bytes != TINY3TPU_ARGMAX_PARAMETER_BYTES)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    parameter = runtime->model + operation->parameter_offset;
    if (read_u32(parameter, 0U) != 0U)
        return TINY3TPU_RUNTIME_UNSUPPORTED;
    if (read_u32(parameter, 4U) != 0U)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    if (source.layout != TINY3TPU_LAYOUT_PACKED ||
        destination.layout != TINY3TPU_LAYOUT_PACKED)
        return TINY3TPU_RUNTIME_UNSUPPORTED;
    if (source.rank != 1U || destination.rank != 1U ||
        destination.dims[0] != 1U || destination.dtype != TINY3TPU_DTYPE_I32 ||
        (source.dtype != TINY3TPU_DTYPE_I8 &&
         source.dtype != TINY3TPU_DTYPE_U8 &&
         source.dtype != TINY3TPU_DTYPE_I32) ||
        source.dims[0] == 0U ||
        !products_fit_u32(source.dims[0], 1U,
                           source.dtype == TINY3TPU_DTYPE_I32 ?
                               (uint32_t)sizeof(int32_t) : 1U,
                           &source_bytes_expected) ||
        source.byte_size != source_bytes_expected ||
        destination.byte_size != sizeof(int32_t))
        return TINY3TPU_RUNTIME_BAD_MODEL;
    element_count = source.dims[0];
    status = tensor_data_pointer(runtime, &source, &source_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = activation_pointer(runtime, &destination, &destination_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    best_value = read_element_as_i32(source_bytes, source.dtype, 0U);
    for (index = 1U; index < element_count; ++index) {
        const int32_t value = read_element_as_i32(source_bytes, source.dtype,
                                                   index);
        /* Strictly greater preserves the first index on ties, matching the
         * compiler reference executor and JAX argmax convention here. */
        if (value > best_value) {
            best_value = value;
            best_index = index;
        }
    }
    write_i32(destination_bytes, (int32_t)best_index);
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_init(tiny3tpu_runtime *runtime,
                                               const tiny3tpu_qgemm_backend *backend)
{
    if (runtime == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    memset(runtime, 0, sizeof(*runtime));
    runtime->backend = backend;
    runtime->initialized = 1U;
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_load_model(tiny3tpu_runtime *runtime,
                                                    const uint8_t *model,
                                                    uint32_t model_bytes)
{
    tiny3tpu_model_header_view header;
    tiny3tpu_runtime_model parsed;
    uint32_t tensor_table_bytes;
    uint32_t operation_table_bytes;
    uint32_t tensor_table_end = 0U;
    uint32_t operation_table_end = 0U;
    uint32_t parameter_end = 0U;
    uint32_t constant_end = 0U;
    uint32_t arena_end = 0U;
    uint32_t next_parameter_offset;
    uint32_t input_flags = 0U;
    uint32_t output_flags = 0U;
    uint32_t index;

    if (runtime == NULL || model == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (model_bytes < TINY3TPU_MODEL_HEADER_BYTES)
        return TINY3TPU_RUNTIME_BAD_MODEL;

    parse_header(model, &header);
    if (header.magic != TINY3TPU_MODEL_MAGIC ||
        header.version != TINY3TPU_MODEL_VERSION ||
        header.header_bytes != TINY3TPU_MODEL_HEADER_BYTES ||
        header.total_bytes != model_bytes)
        return TINY3TPU_RUNTIME_BAD_MODEL;

    if (header.tensor_count > UINT32_MAX / TINY3TPU_MODEL_TENSOR_RECORD_BYTES ||
        header.operation_count > UINT32_MAX / TINY3TPU_MODEL_OPERATION_RECORD_BYTES)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    tensor_table_bytes = header.tensor_count * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
    operation_table_bytes = header.operation_count * TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
    if (!section_end(header.tensor_table_offset, tensor_table_bytes, model_bytes,
                     &tensor_table_end) ||
        !section_end(header.operation_table_offset, operation_table_bytes,
                     model_bytes, &operation_table_end) ||
        !section_end(header.parameter_offset, header.parameter_bytes,
                     model_bytes, &parameter_end) ||
        !section_end(header.constant_offset, header.constant_bytes,
                     model_bytes, &constant_end) ||
        !section_end(header.arena_offset, header.arena_bytes, model_bytes,
                     &arena_end) ||
        !range_is_inside(header.scratch_offset, header.scratch_bytes,
                         model_bytes))
        return TINY3TPU_RUNTIME_BAD_MODEL;

    if (header.scratch_bytes != 0U || header.scratch_offset != 0U ||
        header.flags != 0U ||
        header.input_count == 0U || header.output_count == 0U ||
        header.input_count > header.tensor_count ||
        header.output_count > header.tensor_count ||
        header.tensor_table_offset != TINY3TPU_MODEL_HEADER_BYTES ||
        tensor_table_end != header.operation_table_offset ||
        operation_table_end != header.parameter_offset ||
        parameter_end != header.constant_offset ||
        constant_end != header.arena_offset ||
        arena_end != model_bytes ||
        (header.tensor_table_offset & 3U) != 0U ||
        (header.operation_table_offset & 3U) != 0U ||
        (header.parameter_offset & 3U) != 0U ||
        (header.constant_offset & 3U) != 0U ||
        (header.arena_offset & 15U) != 0U)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    if (crc32_model(model, model_bytes) != header.crc32)
        return TINY3TPU_RUNTIME_BAD_MODEL;

    next_parameter_offset = header.parameter_offset;

    for (index = 0U; index < header.tensor_count; ++index) {
        const uint8_t *record = model + header.tensor_table_offset +
                                index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
        uint32_t dims[TINY3TPU_MAX_TENSOR_DIMS];
        uint32_t expected_bytes;
        uint32_t other;
        const uint32_t id = read_u32(record, TINY3TPU_TENSOR_ID_OFFSET);
        const uint32_t data_offset = read_u32(record, TINY3TPU_TENSOR_BYTE_OFFSET);
        const uint32_t data_bytes = read_u32(record, TINY3TPU_TENSOR_BYTE_SIZE_OFFSET);
        const uint8_t dtype = record[TINY3TPU_TENSOR_META_OFFSET];
        const uint8_t rank = record[TINY3TPU_TENSOR_META_OFFSET + 1U];
        const uint8_t layout = record[TINY3TPU_TENSOR_META_OFFSET + 2U];
        const uint8_t flags = record[TINY3TPU_TENSOR_META_OFFSET + 3U];
        uint32_t data_end;

        if (id == UINT32_MAX || dtype < TINY3TPU_DTYPE_I8 ||
            dtype > TINY3TPU_DTYPE_I32 || layout > TINY3TPU_LAYOUT_NCHW ||
            rank == 0U || rank > TINY3TPU_MAX_RANK ||
            (flags & ~(TINY3TPU_TENSOR_INPUT | TINY3TPU_TENSOR_OUTPUT |
                       TINY3TPU_TENSOR_CONSTANT | TINY3TPU_TENSOR_SCRATCH)) != 0U ||
            read_u32(record, TINY3TPU_TENSOR_RESERVED0_OFFSET) != 0U ||
            read_u32(record, TINY3TPU_TENSOR_RESERVED1_OFFSET) != 0U ||
            !positive_finite_scale_bits(read_u32(record, TINY3TPU_TENSOR_SCALE_OFFSET)) ||
            read_u32(record, TINY3TPU_TENSOR_ZERO_POINT_OFFSET) != 0U ||
            ((flags & TINY3TPU_TENSOR_OUTPUT) != 0U &&
             (flags & (TINY3TPU_TENSOR_INPUT | TINY3TPU_TENSOR_CONSTANT |
                       TINY3TPU_TENSOR_SCRATCH)) != 0U) ||
            (flags & TINY3TPU_TENSOR_SCRATCH) != 0U ||
            ((flags & TINY3TPU_TENSOR_INPUT) != 0U &&
             (flags & TINY3TPU_TENSOR_CONSTANT) != 0U))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        for (other = 0U; other < TINY3TPU_MAX_TENSOR_DIMS; ++other)
            dims[other] = read_u32(record, TINY3TPU_TENSOR_DIMS_OFFSET + other * 4U);
        for (other = 0U; other < rank; ++other)
            if (dims[other] == 0U) return TINY3TPU_RUNTIME_BAD_MODEL;
        for (; other < TINY3TPU_MAX_TENSOR_DIMS; ++other)
            if (dims[other] != 0U) return TINY3TPU_RUNTIME_BAD_MODEL;
        if (!tensor_byte_size(dtype, dims, rank, &expected_bytes) ||
            data_bytes != expected_bytes ||
            !section_end(data_offset, data_bytes, model_bytes, &data_end))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        for (other = 0U; other < index; ++other) {
            const uint8_t *previous = model + header.tensor_table_offset +
                                       other * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
            const uint32_t previous_offset = read_u32(previous, TINY3TPU_TENSOR_BYTE_OFFSET);
            const uint32_t previous_bytes = read_u32(previous, TINY3TPU_TENSOR_BYTE_SIZE_OFFSET);
            uint32_t previous_end;
            if (read_u32(previous, TINY3TPU_TENSOR_ID_OFFSET) == id)
                return TINY3TPU_RUNTIME_BAD_MODEL;
            if (!section_end(previous_offset, previous_bytes, model_bytes, &previous_end) ||
                ranges_overlap(data_offset, data_end, previous_offset, previous_end))
                return TINY3TPU_RUNTIME_BAD_MODEL;
        }

        if ((flags & TINY3TPU_TENSOR_CONSTANT) != 0U) {
            if (data_offset < header.constant_offset || data_end > constant_end)
                return TINY3TPU_RUNTIME_BAD_MODEL;
        } else {
            if (data_offset < header.arena_offset || data_end > arena_end)
                return TINY3TPU_RUNTIME_BAD_MODEL;
        }
        if ((data_offset & 3U) != 0U ||
            ((flags & TINY3TPU_TENSOR_CONSTANT) == 0U &&
             (data_offset & 15U) != 0U))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        if ((flags & TINY3TPU_TENSOR_INPUT) != 0U) ++input_flags;
        if ((flags & TINY3TPU_TENSOR_OUTPUT) != 0U) ++output_flags;
    }
    if (input_flags != header.input_count || output_flags != header.output_count)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    for (index = 0U; index < header.operation_count; ++index) {
        const uint8_t *record = model + header.operation_table_offset +
                                index * TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
        const uint32_t opcode = read_u32(record, TINY3TPU_OPERATION_OPCODE_OFFSET);
        const uint32_t version = read_u32(record, TINY3TPU_OPERATION_VERSION_OFFSET);
        const uint32_t parameter_offset =
            read_u32(record, TINY3TPU_OPERATION_PARAMETER_OFFSET);
        const uint32_t parameter_bytes =
            read_u32(record, TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET);
        const uint32_t expected_inputs =
            (opcode == TINY3TPU_OP_QGEMM || opcode == TINY3TPU_OP_QCONV2D) ? 3U : 1U;
        uint32_t operand;
        uint32_t output_id;

        if (version != TINY3TPU_MODEL_VERSION ||
            read_u32(record, TINY3TPU_OPERATION_RESERVED_OFFSET) != 0U ||
            (opcode < TINY3TPU_OP_QGEMM || opcode > TINY3TPU_OP_ARGMAX) ||
            (opcode == TINY3TPU_OP_QGEMM &&
             parameter_bytes != TINY3TPU_QGEMM_PARAMETER_BYTES) ||
            (opcode == TINY3TPU_OP_QCONV2D &&
             parameter_bytes != TINY3TPU_QCONV2D_PARAMETER_BYTES) ||
            (opcode == TINY3TPU_OP_MAX_POOL_2D &&
             parameter_bytes != TINY3TPU_MAX_POOL2D_PARAMETER_BYTES) ||
            (opcode == TINY3TPU_OP_RESHAPE &&
             parameter_bytes != TINY3TPU_RESHAPE_PARAMETER_BYTES) ||
            (opcode == TINY3TPU_OP_ARGMAX &&
             parameter_bytes != TINY3TPU_ARGMAX_PARAMETER_BYTES) ||
            parameter_offset != next_parameter_offset ||
            !section_end(parameter_offset, parameter_bytes, model_bytes,
                         &parameter_end) ||
            parameter_offset < header.parameter_offset ||
            parameter_end > header.parameter_offset + header.parameter_bytes ||
            (parameter_offset & 3U) != 0U ||
            !operation_parameter_shape_valid(
                opcode, model + parameter_offset, parameter_bytes))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        for (operand = 0U; operand < 3U; ++operand) {
            const uint32_t id = read_u32(record,
                                         TINY3TPU_OPERATION_INPUTS_OFFSET + operand * 4U);
            if (operand >= expected_inputs) {
                if (id != UINT32_MAX) return TINY3TPU_RUNTIME_BAD_MODEL;
            } else if (id == UINT32_MAX ||
                       !tensor_is_available(model, &header, index, id)) {
                return TINY3TPU_RUNTIME_BAD_MODEL;
            }
        }
        output_id = read_u32(record, TINY3TPU_OPERATION_OUTPUTS_OFFSET);
        if (output_id == UINT32_MAX || !tensor_id_index(model, &header, output_id, NULL))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        for (operand = 0U; operand < index; ++operand) {
            const uint8_t *previous = model + header.operation_table_offset +
                                       operand * TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
            if (read_u32(previous, TINY3TPU_OPERATION_OUTPUTS_OFFSET) == output_id)
                return TINY3TPU_RUNTIME_BAD_MODEL;
        }
        {
            uint32_t output_index;
            const uint8_t *output_record;
            if (!tensor_id_index(model, &header, output_id, &output_index))
                return TINY3TPU_RUNTIME_BAD_MODEL;
            output_record = model + header.tensor_table_offset +
                            output_index * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
            if ((output_record[TINY3TPU_TENSOR_META_OFFSET + 3U] &
                 (TINY3TPU_TENSOR_INPUT | TINY3TPU_TENSOR_CONSTANT |
                  TINY3TPU_TENSOR_SCRATCH)) != 0U)
                return TINY3TPU_RUNTIME_BAD_MODEL;
        }
        if (opcode == TINY3TPU_OP_QGEMM &&
            !qgemm_semantics_valid(
                model, &header, record, model + parameter_offset))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        if (opcode == TINY3TPU_OP_QCONV2D &&
            !qconv2d_semantics_valid(
                model, &header, record, model + parameter_offset))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        if (opcode == TINY3TPU_OP_MAX_POOL_2D &&
            !max_pool2d_semantics_valid(
                model, &header, record, model + parameter_offset))
            return TINY3TPU_RUNTIME_BAD_MODEL;
        if (read_u32(record, TINY3TPU_OPERATION_OUTPUTS_OFFSET + 4U) != UINT32_MAX)
            return TINY3TPU_RUNTIME_BAD_MODEL;
        next_parameter_offset = parameter_end;
    }
    if (next_parameter_offset != header.parameter_offset + header.parameter_bytes)
        return TINY3TPU_RUNTIME_BAD_MODEL;

    memset(&parsed, 0, sizeof(parsed));
    parsed.header = header;
    parsed.bytes = model;
    parsed.tensor_table = model + header.tensor_table_offset;
    parsed.operation_table = model + header.operation_table_offset;
    parsed.parameter_data = model + header.parameter_offset;
    parsed.constant_data = model + header.constant_offset;
    parsed.arena_data = model + header.arena_offset;

    runtime->parsed_model = parsed;
    runtime->model = model;
    runtime->model_bytes = model_bytes;
    runtime->input_bound = 0U;
    runtime->ran = 0U;
    runtime->input_data = NULL;
    runtime->input_tensor_id = 0U;
    runtime->activation_storage = NULL;
    runtime->activation_storage_bytes = 0U;
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_bind_input(tiny3tpu_runtime *runtime,
                                                    uint32_t tensor_id,
                                                    const int8_t *data,
                                                    uint32_t data_bytes)
{
    tiny3tpu_tensor_view tensor;
    tiny3tpu_runtime_status status;
    uint32_t index;

    if (runtime == NULL || data == NULL || data_bytes == 0U)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (!runtime_is_ready(runtime)) return TINY3TPU_RUNTIME_NOT_READY;
    status = TINY3TPU_RUNTIME_BAD_ARGUMENT;
    for (index = 0U; index < runtime->parsed_model.header.tensor_count; ++index) {
        if (get_tensor_record(runtime, index, &tensor) == TINY3TPU_RUNTIME_OK &&
            tensor.id == tensor_id) {
            status = TINY3TPU_RUNTIME_OK;
            break;
        }
    }
    if (status != TINY3TPU_RUNTIME_OK ||
        (tensor.flags & TINY3TPU_TENSOR_INPUT) == 0U ||
        data_bytes != tensor.byte_size)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    runtime->input_bound = 1U;
    runtime->input_data = data;
    runtime->input_tensor_id = tensor_id;
    runtime->ran = 0U;
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_bind_workspace(
    tiny3tpu_runtime *runtime, uint8_t *storage, uint32_t storage_bytes)
{
    if (runtime == NULL || storage == NULL || storage_bytes == 0U)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    runtime->activation_storage = storage;
    runtime->activation_storage_bytes = storage_bytes;
    runtime->ran = 0U;
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_run(tiny3tpu_runtime *runtime)
{
    tiny3tpu_tensor_view input;
    uint8_t *input_bytes;
    uint32_t operation_index;
    tiny3tpu_runtime_status status;

    if (runtime == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (!runtime_is_ready(runtime) || runtime->input_bound == 0U)
        return TINY3TPU_RUNTIME_NOT_READY;
    if (runtime->parsed_model.header.operation_count == 0U)
        return TINY3TPU_RUNTIME_BAD_MODEL;
    if (runtime->parsed_model.header.input_count != 1U)
        return TINY3TPU_RUNTIME_UNSUPPORTED;
    if (runtime->activation_storage == NULL ||
        runtime->activation_storage_bytes < runtime->parsed_model.header.arena_bytes)
        return TINY3TPU_RUNTIME_NO_MEMORY;
    status = find_tensor_by_id(runtime, runtime->input_tensor_id, &input);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    status = activation_pointer(runtime, &input, &input_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    memcpy(input_bytes, runtime->input_data, input.byte_size);
    runtime->ran = 0U;
    for (operation_index = 0U;
         operation_index < runtime->parsed_model.header.operation_count;
         ++operation_index) {
        tiny3tpu_operation_view operation;
        status = get_operation_record(runtime, operation_index, &operation);
        if (status != TINY3TPU_RUNTIME_OK) return status;
        if (operation.opcode == TINY3TPU_OP_QGEMM)
            status = execute_qgemm(runtime, &operation);
        else if (operation.opcode == TINY3TPU_OP_QCONV2D)
            status = execute_qconv2d(runtime, &operation);
        else if (operation.opcode == TINY3TPU_OP_MAX_POOL_2D)
            status = execute_max_pool2d(runtime, &operation);
        else if (operation.opcode == TINY3TPU_OP_RESHAPE)
            status = execute_reshape(runtime, &operation);
        else if (operation.opcode == TINY3TPU_OP_ARGMAX)
            status = execute_argmax(runtime, &operation);
        else
            status = TINY3TPU_RUNTIME_UNSUPPORTED;
        if (status != TINY3TPU_RUNTIME_OK) return status;
    }
    runtime->ran = 1U;
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_read_output(tiny3tpu_runtime *runtime,
                                                     uint32_t tensor_id,
                                                     int32_t *data,
                                                     uint32_t element_count)
{
    tiny3tpu_tensor_view tensor;
    uint8_t *output_bytes;
    uint32_t index;
    tiny3tpu_runtime_status status;

    if (runtime == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (data == NULL || element_count == 0U)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (runtime->ran == 0U) return TINY3TPU_RUNTIME_NOT_READY;
    status = find_tensor_by_id(runtime, tensor_id, &tensor);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    if ((tensor.flags & TINY3TPU_TENSOR_OUTPUT) == 0U ||
        (tensor.dtype != TINY3TPU_DTYPE_I32 && tensor.dtype != TINY3TPU_DTYPE_I8) ||
        ((tensor.dtype == TINY3TPU_DTYPE_I32 &&
          (element_count > UINT32_MAX / (uint32_t)sizeof(int32_t) ||
           tensor.byte_size != element_count * sizeof(int32_t))) ||
         (tensor.dtype == TINY3TPU_DTYPE_I8 && tensor.byte_size != element_count)))
        return TINY3TPU_RUNTIME_UNSUPPORTED;
    status = activation_pointer(runtime, &tensor, &output_bytes);
    if (status != TINY3TPU_RUNTIME_OK) return status;
    for (index = 0U; index < element_count; ++index)
        data[index] = tensor.dtype == TINY3TPU_DTYPE_I8
                          ? (int32_t)((const int8_t *)output_bytes)[index]
                          : read_i32(output_bytes + index * 4U);
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_get_model(
    const tiny3tpu_runtime *runtime, const tiny3tpu_runtime_model **model)
{
    if (runtime == NULL || model == NULL) return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (!runtime_is_ready(runtime)) return TINY3TPU_RUNTIME_NOT_READY;
    *model = &runtime->parsed_model;
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_runtime_get_tensor(
    const tiny3tpu_runtime *runtime, uint32_t index, tiny3tpu_tensor_view *tensor)
{
    return get_tensor_record(runtime, index, tensor);
}

tiny3tpu_runtime_status tiny3tpu_runtime_get_operation(
    const tiny3tpu_runtime *runtime, uint32_t index, tiny3tpu_operation_view *operation)
{
    return get_operation_record(runtime, index, operation);
}

tiny3tpu_runtime_status tiny3tpu_runtime_get_tensor_data(
    const tiny3tpu_runtime *runtime, uint32_t tensor_id, const uint8_t **data,
    uint32_t *data_bytes)
{
    tiny3tpu_tensor_view tensor;
    uint32_t index;

    if (runtime == NULL || data == NULL || data_bytes == NULL)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (runtime->initialized == 0U) return TINY3TPU_RUNTIME_NOT_INITIALIZED;
    if (!runtime_is_ready(runtime)) return TINY3TPU_RUNTIME_NOT_READY;
    for (index = 0U; index < runtime->parsed_model.header.tensor_count; ++index) {
        if (get_tensor_record(runtime, index, &tensor) == TINY3TPU_RUNTIME_OK &&
            tensor.id == tensor_id) {
            *data = runtime->model + tensor.byte_offset;
            *data_bytes = tensor.byte_size;
            return TINY3TPU_RUNTIME_OK;
        }
    }
    *data = NULL;
    *data_bytes = 0U;
    return TINY3TPU_RUNTIME_BAD_ARGUMENT;
}

tiny3tpu_runtime_status tiny3tpu_runtime_get_operation_parameters(
    const tiny3tpu_runtime *runtime, uint32_t index, const uint8_t **data,
    uint32_t *data_bytes)
{
    tiny3tpu_operation_view operation;
    tiny3tpu_runtime_status status;

    if (runtime == NULL || data == NULL || data_bytes == NULL)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    status = get_operation_record(runtime, index, &operation);
    if (status != TINY3TPU_RUNTIME_OK) {
        *data = NULL;
        *data_bytes = 0U;
        return status;
    }
    *data = runtime->model + operation.parameter_offset;
    *data_bytes = operation.parameter_bytes;
    return TINY3TPU_RUNTIME_OK;
}
