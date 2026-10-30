"""Fixed-shape two-core MMIO kernels; outer tile loops keep code size bounded.

The compiler's int8 inputs and int32 output contract bounds K by 131071, so
retained partials and their final merge fit int32. Kernels read/write the
compiler workspace directly, without intermediate byte or accumulator buffers.
"""


def tile_schedule(m, k, n):
    ceil = lambda x, y: (x + y - 1) // y
    return min((('rows', ceil(m, 8) * ceil(k, 4) * ceil(n, 4)),
                ('k', ceil(m, 4) * ceil(k, 8) * ceil(n, 4)),
                ('columns', ceil(m, 4) * ceil(k, 4) * ceil(n, 8))),
               key=lambda item: item[1])


def tile_statistics(m, k, n):
    """Required word traffic, assuming one completion poll per launch.

    Counts include zero A words that preserve the second core's retained sum
    on a short K tail. No value-dependent operand caching is assumed.
    """
    ceil = lambda x, y: (x + y - 1) // y
    schedule, launches = tile_schedule(m, k, n)
    a_words = m * ceil(k,8) * ceil(n,4) * 2 if schedule=='k' else m * ceil(k,4) * ceil(n,4)
    k_step = 8 if schedule=='k' else 4
    if k <= k_step:
        b_words = k * ceil(n,4) * (ceil(min(m,8),4) if schedule=='rows' else 1)
    else:
        b_words = k * ceil(n,4) * ceil(m,4)
    reads = m * n * (2 if schedule=='k' else 1)
    return dict(schedule=schedule,launches=launches,operand_word_writes=a_words+b_words,
                result_reads=reads,register_transactions_min=1+a_words+b_words+2*launches+reads)


def emit_mmio_kernel(name, context_type, word_type, m, k, n,
                     lhs, rhs, output, ref, packed_a=None, packed_b=None,
                     batch_expression='context->batch',base_pointers=False):
    """Emit bounded full/tail tile loops and statically assign each core/lane.

    ref resolves workspace values, constants and static index views. Packed
    constants use the existing schedule-independent numeric row-word layout.
    """
    schedule, launches = tile_schedule(m, k, n)
    rs, ks, cs = (8 if schedule == 'rows' else 4,
                  8 if schedule == 'k' else 4,
                  8 if schedule == 'columns' else 4)
    kt = (k + 3) // 4
    code = [f'static int {name}(tiny3tpu_mmio *io,void *opaque){{',
            'int status=tiny3tpu_mmio_kernel_begin(io);if(status)return status;',
            f'{context_type} *context=({context_type}*)opaque;',
            f'{word_type} *w={"0" if base_pointers else "context->w"};uint32_t batch={batch_expression};',
            '(void)w;(void)batch;', 'uint32_t value;']
    if base_pointers:
        code += [f'{word_type} *lhs_data=context->lhs,*rhs_data=context->rhs,*output_data=context->output;',
                 'const uint32_t *packed_lhs=context->packed_a,*packed_rhs=context->packed_b;',
                 '(void)lhs_data;(void)rhs_data;(void)output_data;(void)packed_lhs;(void)packed_rhs;']

    def sections(size, step, variable, body):
        full = size // step * step
        if full:
            if full > step:
                code.append(f'for(uint32_t {variable}=0;{variable}<{full};{variable}+={step}){{')
            body(variable if full > step else '0', step)
            if full > step:
                code.append('}')
        if size != full:
            body(str(full), size - full)

    def pack(terms):
        return '|'.join(f'((uint32_t)(uint8_t)({term})<<{8 * lane})'
                        for lane, term in enumerate(terms)) or '0U'

    def write(slot, expression):
        code.append(f'if(io->write32(io->user,{0x40 + slot * 4}U,{expression}))return -1;')

    def core_offsets(core):
        return (core * 4 if schedule == 'rows' else 0,
                core * 4 if schedule == 'k' else 0,
                core * 4 if schedule == 'columns' else 0)

    def weights(c, cols, t, inner, rows):
        for core in range(2):
            rb, kb, cb = core_offsets(core)
            if rb >= rows or cb >= cols:
                continue
            if packed_b:
                array, words = packed_b
                count=min(4,max(0,inner-kb))
                if count:
                    code.append(f'for(uint32_t word_row=0;word_row<{count};word_row++){{')
                    expr=f'{array}[batch*{words}+((({c}+{cb})/4)*{kt}+({t}+{kb})/4)*4+word_row]'
                    code.append(f'if(io->write32(io->user,{0x50+core*32}U+word_row*4U,{expr}))return -1;}}')
                continue
            for row in range(min(4, max(0, inner - kb))):
                expr = pack(ref(rhs, f'batch*{k*n}+({t}+{kb+row})*{n}+{c}+{cb+lane}')
                            for lane in range(min(4, cols - cb)))
                write(core * 8 + 4 + row, expr)

    def columns(c, cols):
        # A single K launch leaves B unchanged across all row tiles. Load once
        # instead of comparing sixteen cached row words on every launch.
        if k <= ks:
            weights(c, cols, '0', k, min(m, rs))

        def rows(r, row_count):
            def inner(t, inner_count):
                for core in range(2):
                    rb, kb, cb = core_offsets(core)
                    if rb >= row_count or cb >= cols:
                        continue
                    lanes = min(4,max(0,inner_count-kb))
                    if packed_a and lanes:
                        array,words=packed_a
                        count=min(4,row_count-rb)
                        code.append(f'for(uint32_t word_row=0;word_row<{count};word_row++){{')
                        expr=f'{array}[batch*{words}+((({r}+{rb})/4)*{kt}+({t}+{kb})/4)*4+word_row]'
                        code.append(f'if(io->write32(io->user,{0x40+core*32}U+word_row*4U,{expr}))return -1;}}')
                        continue
                    for row in range(min(4, row_count - rb)):
                        expr = pack(ref(lhs, f'batch*{m*k}+({r}+{rb+row})*{k}+{t}+{kb+lane}')
                                    for lane in range(lanes))
                        # Unused output rows need no A writes. Zero K tails
                        # in used A rows make stale, unused B rows harmless.
                        write(core * 8 + row, expr)
                if k > ks:
                    weights(c, cols, t, inner_count, row_count)
                control = '1U' if t == '0' else '9U' if t.isdigit() else f'({t}==0?1U:9U)'
                code.append(f'if(tiny3tpu_mmio_kernel_start(io,{control}))return -1;')

            sections(k, ks, 'tile_k', inner)
            for core in range(2):
                rb, _, cb = core_offsets(core)
                if rb >= row_count or cb >= cols or (schedule == 'k' and core and k <= 4):
                    continue
                # Keep readback loops compact: each core has a known output
                # rectangle, a fixed register base, and no int64 scratch sums.
                code.append(f'for(uint32_t row=0;row<{min(4,row_count-rb)};row++)'
                            f'for(uint32_t col=0;col<{min(4,cols-cb)};col++){{')
                code.append(f'if(io->read32(io->user,{0x80+core*64}U+row*16U+col*4U,&value))return -1;')
                dest = ref(output, f'batch*{m*n}+({r}+{rb}+row)*{n}+{c}+{cb}+col')
                expr = f'(uint32_t)({dest})+value' if schedule == 'k' and core else 'value'
                code.append(f'{dest}=t3p_i32({expr});}}')

        sections(m, rs, 'tile_row', rows)

    sections(n, cs, 'tile_col', columns)
    code.append('return 0;}')
    return '\n'.join(code), dict(**tile_statistics(m,k,n),
                                prepacked_operands=int(packed_a is not None)+int(packed_b is not None))
