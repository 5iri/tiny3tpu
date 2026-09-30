#include "tiny3tpu_runtime.h"

#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* Handcrafted little-endian ABI, no compiler-generated fixtures or executor
 * reference code. Deliberately keep all expected image results literal. */
enum { MODEL_BYTES = 1024, ARENA = 512, ARENA_BYTES = 512,
       OUTPUT = 128, TENSORS = 80, CONV_OP = 272, CONV_PARAM = 312,
       POOL_OP = 176, POOL_PARAM = 216 };
typedef struct fixture {
    uint8_t bytes[MODEL_BYTES];
    uint32_t op, param, constant, output_id, input_bytes, output_count;
} fixture;
static unsigned checks, failures;

static int check(int ok, const char *name)
{
    ++checks;
    if (!ok) { ++failures; fprintf(stderr, "FAIL: %s\n", name); }
    return ok;
}

static void put(uint8_t *p, uint32_t at, uint32_t value)
{
    unsigned i;
    for (i = 0; i < 4; ++i) p[at + i] = (uint8_t)(value >> (8U * i));
}

static void seal(fixture *f)
{
    uint32_t crc = UINT32_MAX;
    unsigned i, bit;
    put(f->bytes, 76, 0);
    for (i = 0; i < MODEL_BYTES; ++i) {
        crc ^= f->bytes[i];
        for (bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? UINT32_C(0xedb88320) : 0U);
    }
    put(f->bytes, 76, ~crc);
}

static uint32_t tensor(fixture *f, uint32_t id, uint8_t dtype,
                       uint8_t rank, uint8_t layout, uint8_t flags,
                       const uint32_t dims[4], uint32_t offset)
{
    uint32_t at = TENSORS + id * 48U, size = dtype == TINY3TPU_DTYPE_I32 ? 4U : 1U;
    unsigned i;
    put(f->bytes, at, id);
    f->bytes[at + 4] = dtype; f->bytes[at + 5] = rank;
    f->bytes[at + 6] = layout; f->bytes[at + 7] = flags;
    for (i = 0; i < 4; ++i) {
        put(f->bytes, at + 8U + 4U * i, dims[i]);
        if (i < rank) size *= dims[i];
    }
    put(f->bytes, at + 24, offset); put(f->bytes, at + 28, size);
    put(f->bytes, at + 32, UINT32_C(0x3f800000)); /* scale 1 */
    return size;
}

static void build(fixture *f, int conv, const uint32_t in[4],
                  const uint32_t out[4], const uint32_t kernel[4],
                  const uint32_t *params, int requant)
{
    uint32_t param_bytes = conv ? 52U : 36U;
    uint32_t i, weights;
    const uint32_t bias[4] = {out[3], 0, 0, 0};
    memset(f, 0, sizeof(*f));
    f->op = conv ? CONV_OP : POOL_OP;
    f->param = conv ? CONV_PARAM : POOL_PARAM;
    f->constant = f->param + param_bytes;
    f->output_id = conv ? 3U : 1U;
    put(f->bytes, 0, TINY3TPU_MODEL_MAGIC); put(f->bytes, 4, 1);
    put(f->bytes, 8, 80); put(f->bytes, 12, MODEL_BYTES);
    put(f->bytes, 16, conv ? 4U : 2U); put(f->bytes, 20, 1);
    put(f->bytes, 24, TENSORS); put(f->bytes, 28, f->op);
    put(f->bytes, 32, f->param); put(f->bytes, 36, param_bytes);
    put(f->bytes, 40, f->constant); put(f->bytes, 44, ARENA - f->constant);
    put(f->bytes, 48, ARENA); put(f->bytes, 52, ARENA_BYTES);
    put(f->bytes, 64, 1); put(f->bytes, 68, 1);
    f->input_bytes = tensor(f, 0, TINY3TPU_DTYPE_I8, 4,
        TINY3TPU_LAYOUT_NHWC, TINY3TPU_TENSOR_INPUT, in, ARENA);
    if (conv) {
        weights = tensor(f, 1, TINY3TPU_DTYPE_I8, 4,
            TINY3TPU_LAYOUT_PACKED, TINY3TPU_TENSOR_CONSTANT, kernel, f->constant);
        (void)tensor(f, 2, TINY3TPU_DTYPE_I32, 1, TINY3TPU_LAYOUT_PACKED,
            TINY3TPU_TENSOR_CONSTANT, bias, (f->constant + weights + 3U) & ~3U);
    }
    f->output_count = out[0] * out[1] * out[2] * out[3];
    (void)tensor(f, f->output_id, conv && !requant ? TINY3TPU_DTYPE_I32 : TINY3TPU_DTYPE_I8,
        4, TINY3TPU_LAYOUT_NHWC, TINY3TPU_TENSOR_OUTPUT, out, ARENA + OUTPUT);
    put(f->bytes, f->op, conv ? TINY3TPU_OP_QCONV2D : TINY3TPU_OP_MAX_POOL_2D);
    put(f->bytes, f->op + 4, 1); put(f->bytes, f->op + 8, 0);
    put(f->bytes, f->op + 12, conv ? 1U : UINT32_MAX);
    put(f->bytes, f->op + 16, conv ? 2U : UINT32_MAX);
    put(f->bytes, f->op + 20, f->output_id);
    put(f->bytes, f->op + 24, UINT32_MAX);
    put(f->bytes, f->op + 28, f->param); put(f->bytes, f->op + 32, param_bytes);
    for (i = 0; i < param_bytes / 4U; ++i) put(f->bytes, f->param + i * 4U, params[i]);
    seal(f);
}

static void execute(fixture *f, const int8_t *input, const int32_t *expected,
                    tiny3tpu_runtime_status expected_status, const char *name)
{
    /* Offset by one even for int32 image output: software must be byte-safe. */
    _Alignas(int32_t) uint8_t guarded[ARENA_BYTES + 2];
    int32_t output[96];
    tiny3tpu_runtime r;
    uint32_t i;
    seal(f);
    memset(guarded, 0xa5, sizeof(guarded));
    if (!check(tiny3tpu_runtime_init(&r, NULL) == TINY3TPU_RUNTIME_OK &&
        tiny3tpu_runtime_load_model(&r, f->bytes, MODEL_BYTES) == TINY3TPU_RUNTIME_OK &&
        tiny3tpu_runtime_bind_workspace(&r, guarded + 1, ARENA_BYTES) == TINY3TPU_RUNTIME_OK &&
        tiny3tpu_runtime_bind_input(&r, 0, input, f->input_bytes) == TINY3TPU_RUNTIME_OK, name)) return;
    if (!check(tiny3tpu_runtime_run(&r) == expected_status, name)) return;
    check(guarded[0] == 0xa5 && guarded[ARENA_BYTES + 1] == 0xa5, "workspace outer guards");
    if (expected_status != TINY3TPU_RUNTIME_OK) {
        check(tiny3tpu_runtime_read_output(&r, f->output_id, output, f->output_count) ==
              TINY3TPU_RUNTIME_NOT_READY, "failed run does not publish output");
        return;
    }
    if (!check(tiny3tpu_runtime_read_output(&r, f->output_id, output, f->output_count) ==
               TINY3TPU_RUNTIME_OK, name)) return;
    for (i = 0; i < f->output_count; ++i) {
        if (output[i] != expected[i])
            fprintf(stderr, "%s[%u]: got %d, expected %d\n", name, i, output[i], expected[i]);
        check(output[i] == expected[i], name);
    }
    check(memcmp(guarded + 1, input, f->input_bytes) == 0, "input retained");
    for (i = f->input_bytes; i < OUTPUT; ++i)
        check(guarded[i + 1] == 0xa5, "input/output gap guard");
    i = OUTPUT + f->output_count *
        (f->bytes[TENSORS + f->output_id * 48U + 4] == TINY3TPU_DTYPE_I32 ? 4U : 1U);
    for (; i < ARENA_BYTES; ++i) check(guarded[i + 1] == 0xa5, "output tail guard");
}

static void spatial_tests(fixture *conv, fixture *pool)
{
    const uint32_t in[4] = {2, 3, 3, 2}, out[4] = {2, 2, 3, 3};
    const uint32_t kernel[4] = {2, 2, 2, 3};
    const uint32_t cp[13] = {2, 1, 1, 0, 0, 1, 2, 2, 1, 0, 0, 0, 0};
    const int8_t input[] = {1,-1, 2,-2, 3,-3, 4,-4, 5,-5, 6,-6, 7,-7, 8,-8, 9,-9,
                           11,-11, 12,-12, 13,-13, 14,-14, 15,-15, 16,-16, 17,-17, 18,-18, 19,-19};
    const int8_t weights[] = {1,0,1, 0,1,-1, 1,0,1, 0,2,-1,
                             1,0,1, 0,3,-1, 1,0,1, 0,4,-1};
    /* Per patch: sum(channel0)+1, weighted channel1-2,
     * sum(channel0-channel1)+3. Patch top row is padding in output row 0. */
    const int32_t expected[] = {4,-13,9, 6,-20,13, 4,-11,9,
        25,-69,51, 29,-79,59, 16,-35,33,
        24,-83,49, 26,-90,53, 14,-41,29,
        65,-169,131, 69,-179,139, 36,-75,73};
    const uint32_t po[4] = {2, 2, 3, 2};
    const uint32_t pp[9] = {2, 2, 2, 1, 1, 0, 0, 1, 0};
    const int32_t pe[] = {2,-1, 3,-2, 3,-3, 8,-4, 9,-5, 9,-6,
                         12,-11, 13,-12, 13,-13, 18,-14, 19,-15, 19,-16};
    build(conv, 1, in, out, kernel, cp, 0);
    memcpy(conv->bytes + conv->constant, weights, sizeof(weights));
    put(conv->bytes, conv->constant + 24, 1);
    put(conv->bytes, conv->constant + 28, (uint32_t)-2);
    put(conv->bytes, conv->constant + 32, 3);
    execute(conv, input, expected, TINY3TPU_RUNTIME_OK, "conv batch2 channels2->3 asymmetric stride");
    build(pool, 0, in, po, kernel, pp, 0);
    execute(pool, input, pe, TINY3TPU_RUNTIME_OK, "pool batch2 channels2 asymmetric stride");
    {
        const uint32_t pi[4] = {2,1,1,2}, pout[4] = {2,2,2,2};
        const uint32_t pads[9] = {1,1,2,2,2,2,0,0,0};
        const int8_t values[] = {-128,-7,-3,-128};
        const int32_t want[] = {-128,-128,-128,-128,-128,-128,-128,-7,
                               -128,-128,-128,-128,-128,-128,-3,-128};
        fixture f;
        build(&f, 0, pi, pout, kernel, pads, 0);
        execute(&f, values, want, TINY3TPU_RUNTIME_OK, "pool fully padded windows and signed minimum");
    }
}

static void quant_and_overflow_tests(void)
{
    const uint32_t in[4] = {2,1,4,1}, kernel[4] = {1,1,1,1};
    uint32_t p[13] = {1,1,0,0,0,0,1,1,1,1,0,TINY3TPU_QGEMM_FLAG_REQUANT,0};
    const int8_t values[] = {-3,-2,-1,0,1,2,3,127};
    const int32_t identity[] = {-3,-2,-1,0,1,2,3,127};
    const int32_t halves[] = {-2,-1,-1,0,1,1,2,64};
    const int32_t saturated[] = {-128,-128,-100,0,100,127,127,127};
    const int32_t relu[] = {0,0,0,0,100,127,127,127};
    fixture f;
    build(&f, 1, in, in, kernel, p, 1); f.bytes[f.constant] = 1;
    execute(&f, values, identity, TINY3TPU_RUNTIME_OK, "requant negative shift=0 identity");
    put(f.bytes, f.param + 40, 1);
    put(f.bytes, TENSORS + 3 * 48 + 32, UINT32_C(0x40000000)); /* output scale 2 */
    execute(&f, values, halves, TINY3TPU_RUNTIME_OK, "requant positive/negative ties away from zero");
    build(&f, 1, in, in, kernel, p, 1); f.bytes[f.constant] = 100;
    execute(&f, values, saturated, TINY3TPU_RUNTIME_OK, "requant saturation both signs");
    put(f.bytes, f.param + 44, TINY3TPU_QGEMM_FLAG_REQUANT | TINY3TPU_QGEMM_FLAG_RELU);
    execute(&f, values, relu, TINY3TPU_RUNTIME_OK, "requant relu and saturation");
    {
        const uint32_t strided[4] = {2,1,2,1};
        const int32_t want[] = {-3,-1,1,3};
        p[1] = 2;
        build(&f, 1, in, strided, kernel, p, 1); f.bytes[f.constant] = 1;
        execute(&f, values, want, TINY3TPU_RUNTIME_OK, "conv width stride2");
        p[1] = 1;
    }
    {
        const uint32_t one[4] = {1,1,1,1};
        const int8_t positive[] = {1}, negative[] = {-1}, zero[] = {0};
        const int32_t max[] = {INT32_MAX}, min[] = {INT32_MIN};
        p[9] = 0; p[11] = 0;
        build(&f, 1, one, one, kernel, p, 0); f.bytes[f.constant] = 1;
        put(f.bytes, f.constant + 4, INT32_MAX);
        execute(&f, zero, max, TINY3TPU_RUNTIME_OK, "int32 maximum boundary");
        execute(&f, positive, NULL, TINY3TPU_RUNTIME_BACKEND_ERROR, "positive accumulation overflow");
        put(f.bytes, f.constant + 4, (uint32_t)INT32_MIN);
        execute(&f, zero, min, TINY3TPU_RUNTIME_OK, "int32 minimum boundary");
        execute(&f, negative, NULL, TINY3TPU_RUNTIME_BACKEND_ERROR, "negative accumulation overflow");
        p[9] = 1; p[11] = TINY3TPU_QGEMM_FLAG_REQUANT;
        build(&f, 1, one, one, kernel, p, 1); f.bytes[f.constant] = 1;
        put(f.bytes, f.constant + 4, INT32_MAX);
        execute(&f, positive, NULL, TINY3TPU_RUNTIME_BACKEND_ERROR, "overflow precedes int8 saturation");
    }
}

static int backend(void *user, const int8_t *a, const int8_t *b,
                   int32_t *out, uint32_t m, uint32_t k, uint32_t n)
{
    unsigned *calls = user;
    ++*calls;
    if (!check((uintptr_t)out % _Alignof(int32_t) == 0 && m == 2 && k == 1 && n == 1 &&
               a[0] == -2 && a[1] == 4 && b[0] == 3, "callback ABI and alignment")) return -1;
    out[0] = -6; out[1] = 12;
    return 0;
}

static void alignment_tests(void)
{
    const uint32_t in[4] = {2,1,1,1}, kernel[4] = {1,1,1,1};
    const uint32_t p[13] = {1,1,0,0,0,0,1,1,1,0,0,0,0};
    const uint32_t matrix[4] = {2,1,0,0}, weight[4] = {1,1,0,0};
    const int8_t input[] = {-2,4};
    fixture f;
    unsigned misaligned, extra;
    build(&f, 1, in, in, kernel, p, 0);
    /* Reuse the wire scaffolding for a QGEMM alignment regression. */
    put(f.bytes, f.op, TINY3TPU_OP_QGEMM);
    put(f.bytes, f.op + 32, 16); put(f.bytes, 36, 16);
    put(f.bytes, 40, f.param + 16); put(f.bytes, 44, ARENA - f.param - 16);
    memset(f.bytes + f.param, 0, 16);
    (void)tensor(&f, 0, TINY3TPU_DTYPE_I8, 2, TINY3TPU_LAYOUT_PACKED,
                 TINY3TPU_TENSOR_INPUT, matrix, ARENA);
    (void)tensor(&f, 1, TINY3TPU_DTYPE_I8, 2, TINY3TPU_LAYOUT_PACKED,
                 TINY3TPU_TENSOR_CONSTANT, weight, f.constant);
    (void)tensor(&f, 3, TINY3TPU_DTYPE_I32, 2, TINY3TPU_LAYOUT_PACKED,
                 TINY3TPU_TENSOR_OUTPUT, matrix, ARENA + OUTPUT);
    f.bytes[f.constant] = 3; put(f.bytes, f.constant + 4, 7); seal(&f);
    for (misaligned = 0; misaligned <= 1; ++misaligned)
    for (extra = 0; extra <= 1; ++extra) {
        _Alignas(int32_t) uint8_t storage[ARENA_BYTES + 4];
        tiny3tpu_runtime r;
        unsigned calls = 0;
        tiny3tpu_qgemm_backend b = {&calls, backend};
        int32_t output[2];
        tiny3tpu_runtime_status want = !misaligned && !extra ?
            TINY3TPU_RUNTIME_NO_MEMORY : TINY3TPU_RUNTIME_OK;
        memset(storage, 0xa5, sizeof(storage));
        if (!check(tiny3tpu_runtime_init(&r, &b) == TINY3TPU_RUNTIME_OK &&
            tiny3tpu_runtime_load_model(&r, f.bytes, MODEL_BYTES) == TINY3TPU_RUNTIME_OK &&
            tiny3tpu_runtime_bind_workspace(&r, storage + misaligned, ARENA_BYTES + extra) == TINY3TPU_RUNTIME_OK &&
            tiny3tpu_runtime_bind_input(&r, 0, input, sizeof(input)) == TINY3TPU_RUNTIME_OK,
            "QGEMM alignment fixture")) continue;
        check(tiny3tpu_runtime_run(&r) == want, "aligned capacity / unaligned software fallback");
        check(calls == (!misaligned && extra ? 1U : 0U), "callback selection");
        if (want == TINY3TPU_RUNTIME_OK)
            check(tiny3tpu_runtime_read_output(&r, 3, output, 2) == TINY3TPU_RUNTIME_OK &&
                  output[0] == 1 && output[1] == 19, "callback/software agree including bias");
        if (misaligned) check(storage[0] == 0xa5, "unaligned leading guard");
        check(storage[misaligned + ARENA_BYTES + extra] == 0xa5, "backend workspace end guard");
    }
}

static void reject_word(const fixture *base, uint32_t at, uint32_t value, const char *name)
{
    fixture f = *base;
    tiny3tpu_runtime r;
    put(f.bytes, at, value); seal(&f);
    (void)tiny3tpu_runtime_init(&r, NULL);
    check(tiny3tpu_runtime_load_model(&r, f.bytes, MODEL_BYTES) == TINY3TPU_RUNTIME_BAD_MODEL, name);
}

static void invalid_tests(const fixture *conv, const fixture *pool)
{
    unsigned k;
    for (k = 0; k < 2; ++k) {
        const fixture *f = k ? pool : conv;
        uint32_t out = TENSORS + f->output_id * 48U;
        reject_word(f, f->param + (k ? 8U : 0U), 0, "zero stride height");
        reject_word(f, f->param + (k ? 12U : 4U), 0, "zero stride width");
        reject_word(f, f->param + (k ? 0U : 24U), 0, "zero kernel height");
        reject_word(f, f->param + (k ? 4U : 28U), 0, "zero kernel width");
        reject_word(f, f->param + (k ? 32U : 48U), 1, "reserved parameter");
        reject_word(f, f->op + 32, k ? 32U : 48U, "truncated parameter descriptor");
        reject_word(f, f->op + 8, 99, "missing input tensor");
        reject_word(f, out + 8, 1, "batch mismatch");
        reject_word(f, out + 12, 3, "output height mismatch");
        reject_word(f, out + 16, 2, "output width mismatch");
        reject_word(f, out + 20, 1, "output channel mismatch");
        reject_word(f, TENSORS + 4, UINT32_C(0x01020401), "NCHW input rejected");
        reject_word(f, TENSORS + 36, 1, "nonzero zero point");
        reject_word(f, TENSORS + 8, UINT32_MAX, "tensor element product overflow");
        reject_word(f, out + 24, UINT32_MAX - 3U, "tensor offset overflow");
        reject_word(f, 52, UINT32_MAX, "arena range overflow");
        reject_word(f, f->param + (k ? 16U : 8U), UINT32_MAX, "padded dimension overflow");
        /* Width stride is 1: the resulting dimension itself exceeds u32. */
        reject_word(f, f->param + (k ? 20U : 12U), UINT32_MAX, "output spatial dimension exceeds u32");
    }
    reject_word(conv, CONV_PARAM + 32, 2, "groups unsupported");
    reject_word(conv, CONV_PARAM + 44, 4, "invalid conv flag");
    reject_word(conv, CONV_PARAM + 40, 63, "shift exceeds ABI limit");
    reject_word(conv, TENSORS + 48 + 16, 3, "weight input channel mismatch");
    reject_word(conv, TENSORS + 96 + 32, UINT32_C(0x40000000), "bias scale mismatch");
    reject_word(pool, TENSORS + 48 + 32, UINT32_C(0x40000000), "pool scale mismatch");
    {
        fixture f;
        const uint32_t one[4] = {1,1,1,1};
        const uint32_t p[13] = {1,1,0,0,0,0,1,1,1,1,0,TINY3TPU_QGEMM_FLAG_REQUANT,0};
        build(&f, 1, one, one, one, p, 1);
        reject_word(&f, f.param + 36, 0, "requant zero multiplier");
        reject_word(&f, f.param + 36, UINT32_MAX, "requant negative multiplier");
        reject_word(&f, f.param + 36, 2, "requant multiplier disagrees with scales");
        reject_word(&f, f.param + 40, 63, "requant oversized shift");
        reject_word(&f, f.param + 40, UINT32_MAX, "requant encoded negative shift");
    }
}

int main(void)
{
    fixture conv, pool;
    spatial_tests(&conv, &pool);
    quant_and_overflow_tests();
    invalid_tests(&conv, &pool);
    alignment_tests();
    printf("runtime image tests: %u checks, %u failures\n", checks, failures);
    return failures == 0 ? 0 : 1;
}
