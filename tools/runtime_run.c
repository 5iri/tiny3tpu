#include "tiny3tpu_runtime.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

/* Host-only runner. Firmware continues to supply its own fixed buffers. */
int main(int argc, char **argv)
{
    FILE *file = NULL;
    uint8_t *model = NULL, *workspace = NULL;
    int8_t *input = NULL;
    int32_t *output = NULL;
    tiny3tpu_runtime runtime;
    tiny3tpu_tensor_view tensor, input_tensor = {0}, output_tensor = {0};
    const tiny3tpu_runtime_model *view;
    long length;
    uint32_t i, count;
    int result = 1;
    if (argc < 3) {
        fprintf(stderr, "usage: tiny3tpu-run MODEL.t3m INPUT_ELEMENT ...\n");
        return 2;
    }
    file = fopen(argv[1], "rb");
    if (file == NULL || fseek(file, 0, SEEK_END) != 0) goto cleanup;
    length = ftell(file);
    if (length <= 0 || (unsigned long)length > UINT32_MAX ||
        fseek(file, 0, SEEK_SET) != 0) goto cleanup;
    model = malloc((size_t)length);
    if (model == NULL || fread(model, 1U, (size_t)length, file) != (size_t)length)
        goto cleanup;
    if (tiny3tpu_runtime_init(&runtime, NULL) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_load_model(&runtime, model, (uint32_t)length) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_get_model(&runtime, &view) != TINY3TPU_RUNTIME_OK)
        goto cleanup;
    if (view->header.input_count != 1U || view->header.output_count != 1U)
        goto cleanup;
    for (i = 0; i < view->header.tensor_count; ++i) {
        if (tiny3tpu_runtime_get_tensor(&runtime, i, &tensor) != TINY3TPU_RUNTIME_OK)
            goto cleanup;
        if (tensor.flags & TINY3TPU_TENSOR_INPUT) input_tensor = tensor;
        if (tensor.flags & TINY3TPU_TENSOR_OUTPUT) output_tensor = tensor;
    }
    if (input_tensor.dtype != TINY3TPU_DTYPE_I8 ||
        input_tensor.byte_size != (uint32_t)(argc - 2)) goto cleanup;
    input = malloc(input_tensor.byte_size);
    workspace = malloc(view->header.arena_bytes);
    count = output_tensor.byte_size /
            (output_tensor.dtype == TINY3TPU_DTYPE_I32 ? 4U : 1U);
    if ((size_t)count > SIZE_MAX / sizeof(*output)) goto cleanup;
    output = malloc((size_t)count * sizeof(*output));
    if (input == NULL || workspace == NULL || output == NULL) goto cleanup;
    for (i = 0; i < input_tensor.byte_size; ++i) {
        char *end;
        long value = strtol(argv[i + 2U], &end, 10);
        if (*end != '\0' || end == argv[i + 2U] || value < -128 || value > 127)
            goto cleanup;
        input[i] = (int8_t)value;
    }
    if (tiny3tpu_runtime_bind_workspace(&runtime, workspace, view->header.arena_bytes) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_bind_input(&runtime, input_tensor.id, input, input_tensor.byte_size) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_run(&runtime) != TINY3TPU_RUNTIME_OK ||
        tiny3tpu_runtime_read_output(&runtime, output_tensor.id, output, count) != TINY3TPU_RUNTIME_OK)
        goto cleanup;
    for (i = 0; i < count; ++i) printf("%s%ld", i ? " " : "", (long)output[i]);
    putchar('\n');
    result = 0;
cleanup:
    if (file != NULL) fclose(file);
    free(output); free(input); free(workspace); free(model);
    if (result) fprintf(stderr, "runtime model execution failed\n");
    return result;
}
