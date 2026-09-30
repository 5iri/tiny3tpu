#ifndef TINY3TPU_FIRMWARE_RUNTIME_ADAPTER_H
#define TINY3TPU_FIRMWARE_RUNTIME_ADAPTER_H

/*
 * Portable firmware seam for the T3M1 runtime container.
 *
 * This header intentionally includes no vendor BSP headers.  A board port
 * supplies storage and one-byte I/O callbacks, then links this C file with
 * tiny3tpu_runtime.  All storage is caller-owned; the adapter never calls
 * malloc and never retains a callback after the adapter is discarded.
 */

#include <stdint.h>

#include "tiny3tpu_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TINY3TPU_FIRMWARE_RUNTIME_REQUEST_MAGIC UINT32_C(0x31523354) /* T3R1 */
#define TINY3TPU_FIRMWARE_RUNTIME_RESPONSE_MAGIC UINT32_C(0x31533354) /* T3S1 */

enum tiny3tpu_firmware_runtime_command {
    TINY3TPU_FIRMWARE_RUNTIME_LOAD = 1U,
    TINY3TPU_FIRMWARE_RUNTIME_BIND_INPUT = 2U,
    TINY3TPU_FIRMWARE_RUNTIME_RUN = 3U,
    TINY3TPU_FIRMWARE_RUNTIME_READ_OUTPUT = 4U
};

typedef int (*tiny3tpu_firmware_runtime_read_u8)(void *user, uint8_t *value);
typedef int (*tiny3tpu_firmware_runtime_write_u8)(void *user, uint8_t value);

typedef struct tiny3tpu_firmware_runtime_io {
    void *user;
    tiny3tpu_firmware_runtime_read_u8 read_u8;
    tiny3tpu_firmware_runtime_write_u8 write_u8;
} tiny3tpu_firmware_runtime_io;

typedef struct tiny3tpu_firmware_runtime_adapter_config {
    /* The runtime borrows this backend pointer until reinitialization. */
    const tiny3tpu_qgemm_backend *backend;
    uint8_t *model_storage;
    uint8_t *model_staging;
    uint32_t model_capacity;
    uint8_t *workspace;
    uint32_t workspace_capacity;
    int8_t *input_storage;
    uint32_t input_capacity;
    int32_t *output_storage;
    uint32_t output_capacity_elements;
} tiny3tpu_firmware_runtime_adapter_config;

typedef struct tiny3tpu_firmware_runtime_adapter {
    tiny3tpu_runtime runtime;
    uint8_t *model_storage;
    uint8_t *model_staging;
    uint32_t model_capacity;
    uint8_t *workspace;
    uint32_t workspace_capacity;
    int8_t *input_storage;
    uint32_t input_capacity;
    int32_t *output_storage;
    uint32_t output_capacity_elements;
    uint32_t initialized;
} tiny3tpu_firmware_runtime_adapter;

tiny3tpu_runtime_status tiny3tpu_firmware_runtime_adapter_init(
    tiny3tpu_firmware_runtime_adapter *adapter,
    const tiny3tpu_firmware_runtime_adapter_config *config);

/*
 * Handle one command after the request magic has already been consumed.
 * The command and its little-endian arguments are read from io.  A response
 * is written for every syntactically complete command:
 *
 *   T3S1, s32 status, u32 value_count, value_count little-endian s32 values
 *
 * LOAD:         u32 model_bytes, model bytes
 * BIND_INPUT:   u32 tensor_id, u32 byte_count, input bytes
 * RUN:          no arguments
 * READ_OUTPUT:  u32 tensor_id, u32 element_count
 *
 * The function returns the runtime status (or BAD_ARGUMENT for an I/O
 * failure).  If a command is truncated, no partial model is committed.
 */
tiny3tpu_runtime_status tiny3tpu_firmware_runtime_handle_command(
    tiny3tpu_firmware_runtime_adapter *adapter,
    const tiny3tpu_firmware_runtime_io *io);

#ifdef __cplusplus
}
#endif

#endif
