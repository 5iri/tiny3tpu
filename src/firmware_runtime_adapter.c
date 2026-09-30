#include "tiny3tpu_firmware_runtime_adapter.h"

#include <stddef.h>
#include <string.h>

static int read_byte(const tiny3tpu_firmware_runtime_io *io, uint8_t *value)
{
    if (io == NULL || io->read_u8 == NULL || value == NULL ||
        io->read_u8(io->user, value) != 0) {
        return 0;
    }
    return 1;
}

static int write_byte(const tiny3tpu_firmware_runtime_io *io, uint8_t value)
{
    return io != NULL && io->write_u8 != NULL &&
           io->write_u8(io->user, value) == 0;
}

static int read_u32(const tiny3tpu_firmware_runtime_io *io, uint32_t *value)
{
    uint8_t bytes[4];
    uint32_t index;

    if (value == NULL) return 0;
    for (index = 0U; index < 4U; ++index)
        if (!read_byte(io, &bytes[index])) return 0;
    *value = (uint32_t)bytes[0] |
             ((uint32_t)bytes[1] << 8U) |
             ((uint32_t)bytes[2] << 16U) |
             ((uint32_t)bytes[3] << 24U);
    return 1;
}

static int write_u32(const tiny3tpu_firmware_runtime_io *io, uint32_t value)
{
    return write_byte(io, (uint8_t)value) &&
           write_byte(io, (uint8_t)(value >> 8U)) &&
           write_byte(io, (uint8_t)(value >> 16U)) &&
           write_byte(io, (uint8_t)(value >> 24U));
}

static int write_response(const tiny3tpu_firmware_runtime_io *io,
                          tiny3tpu_runtime_status status,
                          const int32_t *values, uint32_t value_count)
{
    uint32_t index;

    if (values == NULL) value_count = 0U;
    if (!write_u32(io, TINY3TPU_FIRMWARE_RUNTIME_RESPONSE_MAGIC) ||
        !write_u32(io, (uint32_t)(int32_t)status) ||
        !write_u32(io, value_count))
        return 0;
    for (index = 0U; index < value_count; ++index)
        if (!write_u32(io, (uint32_t)values[index])) return 0;
    return 1;
}

tiny3tpu_runtime_status tiny3tpu_firmware_runtime_adapter_init(
    tiny3tpu_firmware_runtime_adapter *adapter,
    const tiny3tpu_firmware_runtime_adapter_config *config)
{
    if (adapter == NULL || config == NULL || config->model_storage == NULL ||
        config->model_staging == NULL || config->model_capacity == 0U ||
        config->workspace == NULL ||
        config->workspace_capacity == 0U || config->input_storage == NULL ||
        config->input_capacity == 0U || config->output_storage == NULL ||
        config->output_capacity_elements == 0U)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;

    memset(adapter, 0, sizeof(*adapter));
    adapter->model_storage = config->model_storage;
    adapter->model_staging = config->model_staging;
    adapter->model_capacity = config->model_capacity;
    adapter->workspace = config->workspace;
    adapter->workspace_capacity = config->workspace_capacity;
    adapter->input_storage = config->input_storage;
    adapter->input_capacity = config->input_capacity;
    adapter->output_storage = config->output_storage;
    adapter->output_capacity_elements = config->output_capacity_elements;
    if (tiny3tpu_runtime_init(&adapter->runtime, config->backend) !=
        TINY3TPU_RUNTIME_OK)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    adapter->initialized = 1U;
    return TINY3TPU_RUNTIME_OK;
}

tiny3tpu_runtime_status tiny3tpu_firmware_runtime_handle_command(
    tiny3tpu_firmware_runtime_adapter *adapter,
    const tiny3tpu_firmware_runtime_io *io)
{
    uint32_t command;
    tiny3tpu_runtime_status status;

    if (adapter == NULL || io == NULL || adapter->initialized == 0U ||
        io->read_u8 == NULL || io->write_u8 == NULL)
        return TINY3TPU_RUNTIME_BAD_ARGUMENT;
    if (!read_u32(io, &command)) return TINY3TPU_RUNTIME_BAD_ARGUMENT;

    switch (command) {
    case TINY3TPU_FIRMWARE_RUNTIME_LOAD: {
        uint32_t model_bytes;
        uint32_t index;
        if (!read_u32(io, &model_bytes) || model_bytes == 0U ||
            model_bytes > adapter->model_capacity)
            return TINY3TPU_RUNTIME_BAD_ARGUMENT;
        for (index = 0U; index < model_bytes; ++index)
            if (!read_byte(io, &adapter->model_staging[index]))
                return TINY3TPU_RUNTIME_BAD_ARGUMENT;
        status = tiny3tpu_runtime_load_model(&adapter->runtime,
                                             adapter->model_staging,
                                             model_bytes);
        if (status == TINY3TPU_RUNTIME_OK) {
            memcpy(adapter->model_storage, adapter->model_staging, model_bytes);
            status = tiny3tpu_runtime_load_model(&adapter->runtime,
                                                 adapter->model_storage,
                                                 model_bytes);
        }
        (void)write_response(io, status, NULL, 0U);
        return status;
    }
    case TINY3TPU_FIRMWARE_RUNTIME_BIND_INPUT: {
        uint32_t tensor_id;
        uint32_t data_bytes;
        uint32_t index;
        if (!read_u32(io, &tensor_id) || !read_u32(io, &data_bytes) ||
            data_bytes == 0U || data_bytes > adapter->input_capacity)
            return TINY3TPU_RUNTIME_BAD_ARGUMENT;
        for (index = 0U; index < data_bytes; ++index)
            if (!read_byte(io, (uint8_t *)&adapter->input_storage[index]))
                return TINY3TPU_RUNTIME_BAD_ARGUMENT;
        status = tiny3tpu_runtime_bind_input(&adapter->runtime, tensor_id,
                                             adapter->input_storage, data_bytes);
        (void)write_response(io, status, NULL, 0U);
        return status;
    }
    case TINY3TPU_FIRMWARE_RUNTIME_RUN:
        status = tiny3tpu_runtime_bind_workspace(
            &adapter->runtime, adapter->workspace, adapter->workspace_capacity);
        if (status == TINY3TPU_RUNTIME_OK)
            status = tiny3tpu_runtime_run(&adapter->runtime);
        (void)write_response(io, status, NULL, 0U);
        return status;
    case TINY3TPU_FIRMWARE_RUNTIME_READ_OUTPUT: {
        uint32_t tensor_id;
        uint32_t element_count;
        if (!read_u32(io, &tensor_id) || !read_u32(io, &element_count) ||
            element_count == 0U ||
            element_count > adapter->output_capacity_elements)
            return TINY3TPU_RUNTIME_BAD_ARGUMENT;
        status = tiny3tpu_runtime_read_output(&adapter->runtime, tensor_id,
                                              adapter->output_storage,
                                              element_count);
        if (!write_response(io, status,
                            status == TINY3TPU_RUNTIME_OK
                                ? adapter->output_storage : NULL,
                            status == TINY3TPU_RUNTIME_OK ? element_count : 0U))
            return TINY3TPU_RUNTIME_BAD_ARGUMENT;
        return status;
    }
    default:
        status = TINY3TPU_RUNTIME_UNSUPPORTED;
        (void)write_response(io, status, NULL, 0U);
        return status;
    }
}
