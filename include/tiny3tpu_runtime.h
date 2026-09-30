#ifndef TINY3TPU_RUNTIME_H
#define TINY3TPU_RUNTIME_H

#include <stdint.h>
#include "tiny3tpu_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum tiny3tpu_runtime_status {
    TINY3TPU_RUNTIME_OK = 0,
    TINY3TPU_RUNTIME_BAD_ARGUMENT = -1,
    TINY3TPU_RUNTIME_NOT_INITIALIZED = -2,
    TINY3TPU_RUNTIME_BAD_MODEL = -3,
    TINY3TPU_RUNTIME_UNSUPPORTED = -4,
    TINY3TPU_RUNTIME_NOT_READY = -5,
    TINY3TPU_RUNTIME_NO_MEMORY = -6,
    TINY3TPU_RUNTIME_BACKEND_ERROR = -7
} tiny3tpu_runtime_status;

typedef struct tiny3tpu_qgemm_backend {
    void *user;
    /* Optional signed-int8 QGEMM callback: A[M,K], B[K,N], native int32
     * output[M,N]. Return zero on success. Bias is applied by the runtime.
     * Unaligned output storage uses the portable software path. */
    int (*run)(void *user, const int8_t *a, const int8_t *b,
               int32_t *out, uint32_t m, uint32_t k, uint32_t n);
} tiny3tpu_qgemm_backend;

typedef struct tiny3tpu_runtime_model {
    tiny3tpu_model_header_view header;
    const uint8_t *bytes;
    const uint8_t *tensor_table;
    const uint8_t *operation_table;
    const uint8_t *parameter_data;
    const uint8_t *constant_data;
    const uint8_t *arena_data;
} tiny3tpu_runtime_model;

/* Model bytes, backend, input, and activation storage are borrowed. Model
 * bytes remain borrowed until the next successful model load or
 * reinitialization; a failed load preserves the existing borrow. Bind
 * caller-owned activation storage with tiny3tpu_runtime_bind_workspace(); its
 * first byte corresponds to header.arena_offset and it must be at least
 * header.arena_bytes bytes long. No runtime allocation is performed. The
 * software executor supports packed QGEMM with int32 accumulation and
 * optional int8 requantization/ReLU; the hardware callback remains int32. */
typedef struct tiny3tpu_runtime {
    const uint8_t *model;
    uint32_t model_bytes;
    const tiny3tpu_qgemm_backend *backend;
    uint32_t input_bound;
    uint32_t initialized;
    uint32_t ran;
    const int8_t *input_data;
    uint32_t input_tensor_id;
    tiny3tpu_runtime_model parsed_model;
    uint8_t *activation_storage;
    uint32_t activation_storage_bytes;
} tiny3tpu_runtime;

tiny3tpu_runtime_status tiny3tpu_runtime_init(tiny3tpu_runtime *runtime,
                                               const tiny3tpu_qgemm_backend *backend);
tiny3tpu_runtime_status tiny3tpu_runtime_load_model(tiny3tpu_runtime *runtime,
                                                    const uint8_t *model,
                                                    uint32_t model_bytes);
tiny3tpu_runtime_status tiny3tpu_runtime_bind_input(tiny3tpu_runtime *runtime,
                                                    uint32_t tensor_id,
                                                    const int8_t *data,
                                                    uint32_t data_bytes);
tiny3tpu_runtime_status tiny3tpu_runtime_bind_workspace(
    tiny3tpu_runtime *runtime, uint8_t *storage, uint32_t storage_bytes);
tiny3tpu_runtime_status tiny3tpu_runtime_run(tiny3tpu_runtime *runtime);
tiny3tpu_runtime_status tiny3tpu_runtime_read_output(tiny3tpu_runtime *runtime,
                                                     uint32_t tensor_id,
                                                     int32_t *data,
                                                     uint32_t element_count);

tiny3tpu_runtime_status tiny3tpu_runtime_get_model(
    const tiny3tpu_runtime *runtime, const tiny3tpu_runtime_model **model);
tiny3tpu_runtime_status tiny3tpu_runtime_get_tensor(
    const tiny3tpu_runtime *runtime, uint32_t index, tiny3tpu_tensor_view *tensor);
tiny3tpu_runtime_status tiny3tpu_runtime_get_operation(
    const tiny3tpu_runtime *runtime, uint32_t index, tiny3tpu_operation_view *operation);
tiny3tpu_runtime_status tiny3tpu_runtime_get_tensor_data(
    const tiny3tpu_runtime *runtime, uint32_t tensor_id, const uint8_t **data,
    uint32_t *data_bytes);
tiny3tpu_runtime_status tiny3tpu_runtime_get_operation_parameters(
    const tiny3tpu_runtime *runtime, uint32_t index, const uint8_t **data,
    uint32_t *data_bytes);

#ifdef __cplusplus
}
#endif

#endif
