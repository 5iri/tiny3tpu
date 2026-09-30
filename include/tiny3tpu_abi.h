#ifndef TINY3TPU_ABI_H
#define TINY3TPU_ABI_H

/* Shared, C-compatible constants. Wire records are encoded field-by-field;
 * these declarations are documentation and not serialization structs. */
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TINY3TPU_MODEL_MAGIC UINT32_C(0x314D3354) /* "T3M1" */
#define TINY3TPU_MODEL_VERSION UINT32_C(1)
#define TINY3TPU_MODEL_HEADER_BYTES UINT32_C(80)
#define TINY3TPU_MODEL_TENSOR_RECORD_BYTES UINT32_C(48)
#define TINY3TPU_MODEL_OPERATION_RECORD_BYTES UINT32_C(40)
#define TINY3TPU_HEADER_MAGIC_OFFSET UINT32_C(0)
#define TINY3TPU_HEADER_VERSION_OFFSET UINT32_C(4)
#define TINY3TPU_HEADER_BYTES_OFFSET UINT32_C(8)
#define TINY3TPU_HEADER_TOTAL_BYTES_OFFSET UINT32_C(12)
#define TINY3TPU_HEADER_TENSOR_COUNT_OFFSET UINT32_C(16)
#define TINY3TPU_HEADER_OPERATION_COUNT_OFFSET UINT32_C(20)
#define TINY3TPU_HEADER_TENSOR_TABLE_OFFSET UINT32_C(24)
#define TINY3TPU_HEADER_OPERATION_TABLE_OFFSET UINT32_C(28)
#define TINY3TPU_HEADER_PARAMETER_OFFSET UINT32_C(32)
#define TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET UINT32_C(36)
#define TINY3TPU_HEADER_CONSTANT_OFFSET UINT32_C(40)
#define TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET UINT32_C(44)
#define TINY3TPU_HEADER_ARENA_OFFSET UINT32_C(48)
#define TINY3TPU_HEADER_ARENA_BYTES_OFFSET UINT32_C(52)
#define TINY3TPU_HEADER_SCRATCH_OFFSET UINT32_C(56)
#define TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET UINT32_C(60)
#define TINY3TPU_HEADER_INPUT_COUNT_OFFSET UINT32_C(64)
#define TINY3TPU_HEADER_OUTPUT_COUNT_OFFSET UINT32_C(68)
#define TINY3TPU_HEADER_FLAGS_OFFSET UINT32_C(72)
#define TINY3TPU_HEADER_CRC32_OFFSET UINT32_C(76)
/* V1 host-supported operations use no independent scratch allocation. The
 * canonical wire representation is scratch_offset=0 and scratch_bytes=0. */
#define TINY3TPU_TENSOR_ID_OFFSET UINT32_C(0)
#define TINY3TPU_TENSOR_META_OFFSET UINT32_C(4)
#define TINY3TPU_TENSOR_DIMS_OFFSET UINT32_C(8)
#define TINY3TPU_TENSOR_BYTE_OFFSET UINT32_C(24)
#define TINY3TPU_TENSOR_BYTE_SIZE_OFFSET UINT32_C(28)
#define TINY3TPU_TENSOR_SCALE_OFFSET UINT32_C(32)
#define TINY3TPU_TENSOR_ZERO_POINT_OFFSET UINT32_C(36)
#define TINY3TPU_TENSOR_RESERVED0_OFFSET UINT32_C(40)
#define TINY3TPU_TENSOR_RESERVED1_OFFSET UINT32_C(44)
#define TINY3TPU_OPERATION_OPCODE_OFFSET UINT32_C(0)
#define TINY3TPU_OPERATION_VERSION_OFFSET UINT32_C(4)
#define TINY3TPU_OPERATION_INPUTS_OFFSET UINT32_C(8)
#define TINY3TPU_OPERATION_OUTPUTS_OFFSET UINT32_C(20)
#define TINY3TPU_OPERATION_PARAMETER_OFFSET UINT32_C(28)
#define TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET UINT32_C(32)
#define TINY3TPU_OPERATION_RESERVED_OFFSET UINT32_C(36)
#define TINY3TPU_QGEMM_PARAMETER_BYTES UINT32_C(16)
#define TINY3TPU_QCONV2D_PARAMETER_BYTES UINT32_C(52)
#define TINY3TPU_MAX_POOL2D_PARAMETER_BYTES UINT32_C(36)
#define TINY3TPU_RESHAPE_PARAMETER_BYTES UINT32_C(24)
#define TINY3TPU_ARGMAX_PARAMETER_BYTES UINT32_C(8)
#define TINY3TPU_MAX_RANK UINT32_C(4)
#define TINY3TPU_MAX_TENSOR_DIMS UINT32_C(4)

#define TINY3TPU_DTYPE_I8 UINT8_C(1)
#define TINY3TPU_DTYPE_U8 UINT8_C(2)
#define TINY3TPU_DTYPE_I32 UINT8_C(3)

#define TINY3TPU_LAYOUT_PACKED UINT8_C(0)
#define TINY3TPU_LAYOUT_NHWC UINT8_C(1)
#define TINY3TPU_LAYOUT_NCHW UINT8_C(2)

#define TINY3TPU_TENSOR_INPUT UINT8_C(1)
#define TINY3TPU_TENSOR_OUTPUT UINT8_C(2)
#define TINY3TPU_TENSOR_CONSTANT UINT8_C(4)
#define TINY3TPU_TENSOR_SCRATCH UINT8_C(8)

#define TINY3TPU_OP_QGEMM UINT32_C(1)
#define TINY3TPU_OP_QCONV2D UINT32_C(2)
#define TINY3TPU_OP_MAX_POOL_2D UINT32_C(3)
#define TINY3TPU_OP_RESHAPE UINT32_C(4)
#define TINY3TPU_OP_ARGMAX UINT32_C(5)

#define TINY3TPU_QGEMM_FLAG_REQUANT UINT32_C(1)
#define TINY3TPU_QGEMM_FLAG_RELU UINT32_C(2)
#define TINY3TPU_QGEMM_FLAG_WEIGHT_OUT_IN UINT32_C(4)

/* QCONV2D parameters, all little-endian u32 except multiplier (s32):
 * [stride_h, stride_w, pad_top, pad_left, pad_bottom, pad_right,
 *  kernel_h, kernel_w, groups, multiplier, shift, flags, reserved].
 * The portable v1 runtime accepts groups=1. Activations and outputs are
 * rank-4 NHWC. Weights are rank-4 HWIO in packed [KH,KW,CIN,COUT] order.
 * Non-requantized output is int32; the existing REQUANT/RELU flags select
 * signed-int8 output using the same multiplier/shift convention as QGEMM.
 */
#define TINY3TPU_QCONV2D_STRIDE_H_OFFSET UINT32_C(0)
#define TINY3TPU_QCONV2D_STRIDE_W_OFFSET UINT32_C(4)
#define TINY3TPU_QCONV2D_PAD_TOP_OFFSET UINT32_C(8)
#define TINY3TPU_QCONV2D_PAD_LEFT_OFFSET UINT32_C(12)
#define TINY3TPU_QCONV2D_PAD_BOTTOM_OFFSET UINT32_C(16)
#define TINY3TPU_QCONV2D_PAD_RIGHT_OFFSET UINT32_C(20)
#define TINY3TPU_QCONV2D_KERNEL_H_OFFSET UINT32_C(24)
#define TINY3TPU_QCONV2D_KERNEL_W_OFFSET UINT32_C(28)
#define TINY3TPU_QCONV2D_GROUPS_OFFSET UINT32_C(32)
#define TINY3TPU_QCONV2D_MULTIPLIER_OFFSET UINT32_C(36)
#define TINY3TPU_QCONV2D_SHIFT_OFFSET UINT32_C(40)
#define TINY3TPU_QCONV2D_FLAGS_OFFSET UINT32_C(44)
#define TINY3TPU_QCONV2D_RESERVED_OFFSET UINT32_C(48)

/* MAX_POOL_2D parameters, all little-endian u32:
 * [kernel_h, kernel_w, stride_h, stride_w, pad_top, pad_left,
 *  pad_bottom, pad_right, reserved]. Activations are rank-4 NHWC signed
 * int8 tensors. Padding contributes the minimum int8 value (-128), which is
 * the quantized negative-infinity value for max pooling. */
#define TINY3TPU_MAX_POOL2D_KERNEL_H_OFFSET UINT32_C(0)
#define TINY3TPU_MAX_POOL2D_KERNEL_W_OFFSET UINT32_C(4)
#define TINY3TPU_MAX_POOL2D_STRIDE_H_OFFSET UINT32_C(8)
#define TINY3TPU_MAX_POOL2D_STRIDE_W_OFFSET UINT32_C(12)
#define TINY3TPU_MAX_POOL2D_PAD_TOP_OFFSET UINT32_C(16)
#define TINY3TPU_MAX_POOL2D_PAD_LEFT_OFFSET UINT32_C(20)
#define TINY3TPU_MAX_POOL2D_PAD_BOTTOM_OFFSET UINT32_C(24)
#define TINY3TPU_MAX_POOL2D_PAD_RIGHT_OFFSET UINT32_C(28)
#define TINY3TPU_MAX_POOL2D_RESERVED_OFFSET UINT32_C(32)

/* The following are C ABI views for documentation/firmware parsing. They are
 * intentionally never written to or read from the wire as native structs. */
typedef struct tiny3tpu_model_header_view {
    uint32_t magic;
    uint32_t version;
    uint32_t header_bytes;
    uint32_t total_bytes;
    uint32_t tensor_count;
    uint32_t operation_count;
    uint32_t tensor_table_offset;
    uint32_t operation_table_offset;
    uint32_t parameter_offset;
    uint32_t parameter_bytes;
    uint32_t constant_offset;
    uint32_t constant_bytes;
    uint32_t arena_offset;
    uint32_t arena_bytes;
    uint32_t scratch_offset;
    uint32_t scratch_bytes;
    uint32_t input_count;
    uint32_t output_count;
    uint32_t flags;
    uint32_t crc32;
} tiny3tpu_model_header_view;

typedef struct tiny3tpu_tensor_view {
    uint32_t id;
    uint8_t dtype;
    uint8_t rank;
    uint8_t layout;
    uint8_t flags;
    uint32_t dims[4];
    uint32_t byte_offset;
    uint32_t byte_size;
    uint32_t scale_bits;
    int32_t zero_point;
    uint32_t reserved0;
    uint32_t reserved1;
} tiny3tpu_tensor_view;

typedef struct tiny3tpu_operation_view {
    uint32_t opcode;
    uint32_t version;
    uint32_t inputs[3];
    uint32_t outputs[2];
    uint32_t parameter_offset;
    uint32_t parameter_bytes;
    uint32_t reserved;
} tiny3tpu_operation_view;

/* These assertions make the documented C views a useful ABI tripwire while
 * keeping serialization field-by-field and independent of native padding. */
#if defined(__cplusplus)
static_assert(sizeof(tiny3tpu_model_header_view) == 80, "model header view must be 80 bytes");
static_assert(offsetof(tiny3tpu_model_header_view, magic) == TINY3TPU_HEADER_MAGIC_OFFSET, "magic offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, version) == TINY3TPU_HEADER_VERSION_OFFSET, "version offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, header_bytes) == TINY3TPU_HEADER_BYTES_OFFSET, "header size offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, total_bytes) == TINY3TPU_HEADER_TOTAL_BYTES_OFFSET, "total size offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, tensor_count) == TINY3TPU_HEADER_TENSOR_COUNT_OFFSET, "tensor count offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, operation_count) == TINY3TPU_HEADER_OPERATION_COUNT_OFFSET, "operation count offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, tensor_table_offset) == TINY3TPU_HEADER_TENSOR_TABLE_OFFSET, "tensor table offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, operation_table_offset) == TINY3TPU_HEADER_OPERATION_TABLE_OFFSET, "operation table offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, parameter_offset) == TINY3TPU_HEADER_PARAMETER_OFFSET, "parameter offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, parameter_bytes) == TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET, "parameter size offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, constant_offset) == TINY3TPU_HEADER_CONSTANT_OFFSET, "constant offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, constant_bytes) == TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET, "constant size offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, crc32) == 76, "CRC must be at wire offset 76");
static_assert(sizeof(tiny3tpu_tensor_view) == 48, "tensor view must be 48 bytes");
static_assert(sizeof(tiny3tpu_operation_view) == 40, "operation view must be 40 bytes");
static_assert(offsetof(tiny3tpu_model_header_view, arena_offset) == TINY3TPU_HEADER_ARENA_OFFSET, "arena offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, arena_bytes) == TINY3TPU_HEADER_ARENA_BYTES_OFFSET, "arena size mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, scratch_offset) == TINY3TPU_HEADER_SCRATCH_OFFSET, "scratch offset mismatch");
static_assert(offsetof(tiny3tpu_model_header_view, scratch_bytes) == TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET, "scratch size mismatch");
static_assert(offsetof(tiny3tpu_tensor_view, byte_offset) == TINY3TPU_TENSOR_BYTE_OFFSET, "tensor offset mismatch");
static_assert(offsetof(tiny3tpu_tensor_view, byte_size) == TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, "tensor size mismatch");
static_assert(offsetof(tiny3tpu_tensor_view, dims) == TINY3TPU_TENSOR_DIMS_OFFSET, "tensor dimensions offset mismatch");
static_assert(offsetof(tiny3tpu_tensor_view, scale_bits) == TINY3TPU_TENSOR_SCALE_OFFSET, "tensor scale offset mismatch");
static_assert(offsetof(tiny3tpu_tensor_view, zero_point) == TINY3TPU_TENSOR_ZERO_POINT_OFFSET, "tensor zero-point offset mismatch");
static_assert(offsetof(tiny3tpu_operation_view, parameter_offset) == TINY3TPU_OPERATION_PARAMETER_OFFSET, "operation parameter offset mismatch");
static_assert(offsetof(tiny3tpu_operation_view, parameter_bytes) == TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET, "operation parameter size mismatch");
static_assert(offsetof(tiny3tpu_operation_view, inputs) == TINY3TPU_OPERATION_INPUTS_OFFSET, "operation inputs offset mismatch");
static_assert(offsetof(tiny3tpu_operation_view, outputs) == TINY3TPU_OPERATION_OUTPUTS_OFFSET, "operation outputs offset mismatch");
#else
_Static_assert(sizeof(tiny3tpu_model_header_view) == 80, "model header view must be 80 bytes");
_Static_assert(offsetof(tiny3tpu_model_header_view, magic) == TINY3TPU_HEADER_MAGIC_OFFSET, "magic offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, version) == TINY3TPU_HEADER_VERSION_OFFSET, "version offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, header_bytes) == TINY3TPU_HEADER_BYTES_OFFSET, "header size offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, total_bytes) == TINY3TPU_HEADER_TOTAL_BYTES_OFFSET, "total size offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, tensor_count) == TINY3TPU_HEADER_TENSOR_COUNT_OFFSET, "tensor count offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, operation_count) == TINY3TPU_HEADER_OPERATION_COUNT_OFFSET, "operation count offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, tensor_table_offset) == TINY3TPU_HEADER_TENSOR_TABLE_OFFSET, "tensor table offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, operation_table_offset) == TINY3TPU_HEADER_OPERATION_TABLE_OFFSET, "operation table offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, parameter_offset) == TINY3TPU_HEADER_PARAMETER_OFFSET, "parameter offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, parameter_bytes) == TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET, "parameter size offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, constant_offset) == TINY3TPU_HEADER_CONSTANT_OFFSET, "constant offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, constant_bytes) == TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET, "constant size offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, crc32) == 76, "CRC must be at wire offset 76");
_Static_assert(sizeof(tiny3tpu_tensor_view) == 48, "tensor view must be 48 bytes");
_Static_assert(sizeof(tiny3tpu_operation_view) == 40, "operation view must be 40 bytes");
_Static_assert(offsetof(tiny3tpu_model_header_view, arena_offset) == TINY3TPU_HEADER_ARENA_OFFSET, "arena offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, arena_bytes) == TINY3TPU_HEADER_ARENA_BYTES_OFFSET, "arena size mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, scratch_offset) == TINY3TPU_HEADER_SCRATCH_OFFSET, "scratch offset mismatch");
_Static_assert(offsetof(tiny3tpu_model_header_view, scratch_bytes) == TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET, "scratch size mismatch");
_Static_assert(offsetof(tiny3tpu_tensor_view, byte_offset) == TINY3TPU_TENSOR_BYTE_OFFSET, "tensor offset mismatch");
_Static_assert(offsetof(tiny3tpu_tensor_view, byte_size) == TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, "tensor size mismatch");
_Static_assert(offsetof(tiny3tpu_tensor_view, dims) == TINY3TPU_TENSOR_DIMS_OFFSET, "tensor dimensions offset mismatch");
_Static_assert(offsetof(tiny3tpu_tensor_view, scale_bits) == TINY3TPU_TENSOR_SCALE_OFFSET, "tensor scale offset mismatch");
_Static_assert(offsetof(tiny3tpu_tensor_view, zero_point) == TINY3TPU_TENSOR_ZERO_POINT_OFFSET, "tensor zero-point offset mismatch");
_Static_assert(offsetof(tiny3tpu_operation_view, parameter_offset) == TINY3TPU_OPERATION_PARAMETER_OFFSET, "operation parameter offset mismatch");
_Static_assert(offsetof(tiny3tpu_operation_view, parameter_bytes) == TINY3TPU_OPERATION_PARAMETER_BYTES_OFFSET, "operation parameter size mismatch");
_Static_assert(offsetof(tiny3tpu_operation_view, inputs) == TINY3TPU_OPERATION_INPUTS_OFFSET, "operation inputs offset mismatch");
_Static_assert(offsetof(tiny3tpu_operation_view, outputs) == TINY3TPU_OPERATION_OUTPUTS_OFFSET, "operation outputs offset mismatch");
#endif

#ifdef __cplusplus
}
#endif

#endif
