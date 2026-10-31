"""Fixed-shape eight-core MMIO kernels; outer tile loops keep code size bounded.

The compiler's int8 inputs and int32 output contract bounds K by 131071, so
retained partials and their final merge fit int32. Kernels read/write the
compiler workspace directly, without intermediate byte or accumulator buffers.
"""

_SCHEDULES = (
    ('rows', 32, 4, 4),
    ('k', 4, 32, 4),
    ('columns', 4, 4, 32),
    ('grid_2x4', 8, 4, 16),
    ('grid_4x2', 16, 4, 8),
)


def _stats_for_schedule(schedule, rs, ks, cs, m, k, n):
    ceil = lambda x, y: (x + y - 1) // y
    launches = ceil(m, rs) * ceil(k, ks) * ceil(n, cs)
    a_words = (m * ceil(k, 32) * ceil(n, 4) * 8
               if schedule == 'k' else m * ceil(k, 4) * ceil(n, cs))
    b_words = (k * ceil(n, 4)
               if k <= ks else k * ceil(n, 4) * ceil(m, rs))
    reads = m * n * (min(8, ceil(k, 4)) if schedule == 'k' else 1)
    return dict(schedule=schedule, launches=launches,
                operand_word_writes=a_words + b_words,
                result_reads=reads,
                register_transactions_min=1 + a_words + b_words + 2 * launches + reads)


def tile_statistics(m, k, n):
    """Required word traffic, assuming one completion poll per launch.

    Counts include zero A words that preserve active cores' retained sums
    on a short K tail. Shared A/B tiles use hardware broadcast apertures.
    """
    candidates = [_stats_for_schedule(s, rs, ks, cs, m, k, n)
                  for s, rs, ks, cs in _SCHEDULES]
    return min(candidates,
               key=lambda item: (item['launches'], item['register_transactions_min']))


def tile_schedule(m, k, n):
    stats = tile_statistics(m, k, n)
    return stats['schedule'], stats['launches']


_SCHED_MACROS = {
    'rows': 'TINY3TPU_SCHED_ROWS',
    'k': 'TINY3TPU_SCHED_K',
    'columns': 'TINY3TPU_SCHED_COLUMNS',
    'grid_2x4': 'TINY3TPU_SCHED_GRID_2X4',
    'grid_4x2': 'TINY3TPU_SCHED_GRID_4X2',
}


def emit_mmio_kernel(name, context_type, word_type, m, k, n,
                     lhs, rhs, output, ref, packed_a=None, packed_b=None,
                     batch_expression='context->batch', base_pointers=False):
    """Instantiate the pure-C MMIO kernel template in tiny3tpu_mmio_backend.h."""
    schedule, _ = tile_schedule(m, k, n)
    kt = (k + 3) // 4
    a_expr = '0' if packed_a else ref(lhs, f'batch*{m*k}+(_r)*{k}+(_c)')
    b_expr = '0' if packed_b else ref(rhs, f'batch*{k*n}+(_r)*{n}+(_c)')
    out_expr = ref(output, f'batch*{m*n}+(_r)*{n}+(_c)')
    pa_expr = f'{packed_a[0]}[batch*{packed_a[1]}+(_i)]' if packed_a else '0U'
    pb_expr = f'{packed_b[0]}[batch*{packed_b[1]}+(_i)]' if packed_b else '0U'
    macro = 'TINY3TPU_DEFINE_MMIO_KERNEL_PTRS' if base_pointers else 'TINY3TPU_DEFINE_MMIO_KERNEL_CTX'
    code = '\n'.join((
        f'#define T3P_MMIO_A(_r,_c) ({a_expr})',
        f'#define T3P_MMIO_B(_r,_c) ({b_expr})',
        f'#define T3P_MMIO_OUT(_r,_c) {out_expr}',
        f'#define T3P_MMIO_PA(_i) ({pa_expr})',
        f'#define T3P_MMIO_PB(_i) ({pb_expr})',
        f'{macro}({name},{context_type},{word_type},{m}U,{k}U,{n}U,{kt}U,'
        f'{_SCHED_MACROS[schedule]},{1 if packed_a else 0},{1 if packed_b else 0})',
        '#undef T3P_MMIO_A',
        '#undef T3P_MMIO_B',
        '#undef T3P_MMIO_OUT',
        '#undef T3P_MMIO_PA',
        '#undef T3P_MMIO_PB',
    ))
    return code, dict(**tile_statistics(m, k, n),
                      prepacked_operands=int(packed_a is not None) + int(packed_b is not None))
