#include "tiny3tpu_dma.h"
#include <limits.h>
#include <stddef.h>

enum { TX=0, RX=1, BYTES=2, CONTROL=3, STATUS=4, ABI=7 };
enum { TPU_CONTROL=0, UBUF_CFG=4, UBUF_DATA=8, CRD_CFG=12,
       TPU_STATUS=16, RESULT_LO=20, RESULT_HI=24 };

static void ordered_io(void)
{
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
}

int tiny3tpu_dma_init(tiny3tpu_dma *dma)
{
    if (!dma || !dma->registers || !dma->commands || !dma->responses ||
        !dma->poll_limit || !dma->capacity || dma->capacity>8191) return -1;
    dma->poisoned=1;
    if (dma->registers[ABI]!=UINT32_C(0x54444d31) || dma->registers[STATUS]) return -1;
    dma->poisoned=0;
    return 0;
}

int tiny3tpu_dma_submit(tiny3tpu_dma *dma, uint32_t commands)
{
    if (!dma || dma->poisoned || !commands || commands>dma->capacity || commands>8191) return -1;
    const uintptr_t tx=(uintptr_t)dma->commands, rx=(uintptr_t)dma->responses;
    const uint32_t bytes=commands*8;
    if ((tx&3) || (rx&3) || tx<UINT32_C(0x40000000) || rx<UINT32_C(0x40000000) ||
        tx>UINT32_C(0x80000000)-bytes || rx>UINT32_C(0x80000000)-bytes ||
        !(tx+bytes<=rx || rx+bytes<=tx)) return -1;
    if (dma->registers[STATUS]) { dma->poisoned=1; return -1; }
    ordered_io();
    dma->registers[TX]=(uint32_t)tx;
    dma->registers[RX]=(uint32_t)rx;
    dma->registers[BYTES]=bytes;
    dma->registers[CONTROL]=1;
    uint32_t status=0, poll;
    for (poll=0;poll<dma->poll_limit;++poll) {
        status=dma->registers[STATUS];
        if (status&2) break;
    }
    if (poll==dma->poll_limit || (status&1)) { dma->poisoned=1; return -1; }
    ordered_io();
    int failed=(status&12)!=0;
    /* TDM1 aggregates every command/protocol/AXI error before DONE, which
     * also waits for the final response write. Avoid rereading all status
     * words from DDR; callers still consume the required response data. */
    dma->registers[CONTROL]=2;
    ordered_io();
    dma->poisoned=failed;
    return failed ? -1 : 0;
}

/* These small builders execute for every command. Inlining lets RV32 code
 * keep the batch cursor locally and avoids repeated call/return flushes. */
static inline __attribute__((always_inline)) void append(tiny3tpu_dma *dma, uint32_t *count, uint32_t header, uint32_t data)
{
    dma->commands[2*(*count)]=header;
    dma->commands[2*(*count)+1]=data;
    ++*count;
}

static inline __attribute__((always_inline)) void write_command(tiny3tpu_dma *dma, uint32_t *count, uint32_t address, uint32_t value)
{
    append(dma,count,UINT32_C(0xf100)|address,value);
}

#ifndef TINY3TPU_DMA_PACKED_ROWS
static inline __attribute__((always_inline)) void operand(tiny3tpu_dma *dma, uint32_t *count, uint32_t core, uint32_t select_b,
                    uint32_t row, uint32_t col, int8_t value)
{
    write_command(dma,count,UBUF_CFG,select_b|(core<<8)|(row<<16)|(col<<24));
    write_command(dma,count,UBUF_DATA,(uint32_t)(int32_t)value);
    write_command(dma,count,TPU_CONTROL,2);
}

#endif

static int wait_done(tiny3tpu_dma *dma)
{
    int seen_busy=0;
    for (uint32_t poll=0;poll<dma->poll_limit;++poll) {
        uint32_t count=0;
        append(dma,&count,TPU_STATUS,0);
        if (tiny3tpu_dma_submit(dma,count)) return -1;
        uint32_t status=dma->responses[1];
        if (status&2) return 0;
        if (status&1) seen_busy=1;
        else if (seen_busy) return 0;
    }
    dma->poisoned=1;
    return -1;
}

static inline __attribute__((always_inline)) uint32_t result_commands(tiny3tpu_dma *dma, uint32_t row0, uint32_t col0,
                        uint32_t m, uint32_t n)
{
    uint32_t count=0;
    for (uint32_t core=0;core<2;++core) for (uint32_t row=0;row<4 && row0+row<m;++row)
        for (uint32_t col=0;col<4 && col0+col<n;++col) {
            write_command(dma,&count,CRD_CFG,(core<<8)|(row<<16)|(col<<24));
            write_command(dma,&count,TPU_CONTROL,4);
            /* Each bridge write completes before the following read.
             * The fixed accelerator exposes signed 32-bit results;
             * its HI register is just sign extension of this value. */
            append(dma,&count,RESULT_LO,0);
        }
    return count;
}

#ifdef TINY3TPU_DMA_PACKED_ROWS
static inline __attribute__((always_inline)) uint32_t packed_four(const uint8_t *p)
{
    uint32_t word;
    if (((uintptr_t)p&3)==0) {
        /* memcpy preserves C aliasing rules. The guarded alignment promise
         * lets RV32IM use one LW instead of four uncached byte reads. */
        __builtin_memcpy(&word,__builtin_assume_aligned(p,4),sizeof(word));
        return word;
    }
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
#endif

int tiny3tpu_dma_qgemm(void *user, const int8_t *a, const int8_t *b,
                      int32_t *output, uint32_t m, uint32_t k, uint32_t n)
{
    tiny3tpu_dma *dma=user;
#ifdef TINY3TPU_DMA_PACKED_ROWS
    const uint32_t required_capacity=96;
#else
    const uint32_t required_capacity=193;
#endif
    if (!dma || dma->poisoned || dma->capacity<required_capacity || !a || !b || !output || !m || !k || !n ||
        (uint64_t)m*k>SIZE_MAX || (uint64_t)k*n>SIZE_MAX ||
        (uint64_t)m*n>SIZE_MAX/sizeof(*output)) return -1;
    uint32_t count=0;
    append(dma,&count,TPU_STATUS,0);
    if (tiny3tpu_dma_submit(dma,count) || (dma->responses[1]&1)) return -1;
    /* The packed load uses commands 0..16. Keep invariant result commands
     * in a disjoint window, rebuilding only when the output tile shape changes.
     * Descriptors are synchronous; parent poisoning covers both windows. */
    tiny3tpu_dma result_dma;
    tiny3tpu_dma *reader=dma;
    uint32_t result_count=0, cached_rows=0, cached_cols=0;
#ifdef TINY3TPU_DMA_PACKED_ROWS
    const int reuse_results=(k>8 || n>=8 || (m>=8 && n<=4)) && dma->capacity>=113;
#else
    const int reuse_results=0;
#endif
    if (reuse_results) {
        result_dma=*dma;
        result_dma.commands+=34;
        result_dma.responses+=34;
        result_dma.capacity-=17;
        reader=&result_dma;
        /* Polling overwrites command zero only; all other load headers and
         * the final START command survive in the disjoint load window. */
        for (uint32_t core=0;core<2;++core) for (uint32_t row=0;row<4;++row) {
            const uint32_t index=core*16+row*4;
            dma->commands[index]=UINT32_C(0xf140)+core*32+row*4;
            dma->commands[index+2]=UINT32_C(0xf150)+core*32+row*4;
        }
        dma->commands[32]=UINT32_C(0xf100);
        dma->commands[33]=1;
    }
    for (uint32_t row0=0;row0<m;row0+=4) for (uint32_t col0=0;col0<n;col0+=4) {
        int64_t sums[4][4]={{0}};
        if (reuse_results) {
            const uint32_t rows=m-row0<4 ? m-row0 : 4;
            const uint32_t cols=n-col0<4 ? n-col0 : 4;
            if (rows!=cached_rows || cols!=cached_cols) {
                result_count=result_commands(reader,row0,col0,m,n);
                cached_rows=rows;
                cached_cols=cols;
            }
        }
        for (uint32_t inner0=0;inner0<k;) {
            count=0;
#ifdef TINY3TPU_DMA_PACKED_ROWS
            for (uint32_t core=0;core<2;++core) for (uint32_t row=0;row<4;++row) {
                uint32_t packed_a=0, packed_b=0;
                const uint32_t brow=core*4+row;
                if (row0+row<m) {
                    const uint8_t *ap=(const uint8_t *)a+(size_t)(row0+row)*k+inner0;
                    if (core*4+4<=k-inner0) {
                        ap+=core*4;
                        packed_a=packed_four(ap);
                    } else {
                        for (uint32_t col=0;col<4;++col)
                            if (core*4+col<k-inner0) packed_a|=(uint32_t)ap[core*4+col]<<(col*8);
                    }
                }
                if (brow<k-inner0) {
                    const uint8_t *bp=(const uint8_t *)b+(size_t)(inner0+brow)*n+col0;
                    if (n-col0>=4) {
                        packed_b=packed_four(bp);
                    } else {
                        for (uint32_t col=0;col<n-col0;++col) packed_b|=(uint32_t)bp[col]<<(col*8);
                    }
                }
                if (reuse_results) {
                    dma->commands[2*count+1]=packed_a;
                    dma->commands[2*count+3]=packed_b;
                    count+=2;
                } else {
                    write_command(dma,&count,0x40+core*32+row*4,packed_a);
                    write_command(dma,&count,0x50+core*32+row*4,packed_b);
                }
            }
#else
            for (uint32_t core=0;core<2;++core) for (uint32_t row=0;row<4;++row) for (uint32_t col=0;col<4;++col) {
                const uint32_t acol=core*4+col, brow=core*4+row;
                const int8_t av=row0+row<m && acol<k-inner0 ? a[(size_t)(row0+row)*k+inner0+acol] : 0;
                const int8_t bv=brow<k-inner0 && col0+col<n ? b[(size_t)(inner0+brow)*n+col0+col] : 0;
                operand(dma,&count,core,0,row,col,av);
                operand(dma,&count,core,1,row,col,bv);
            }
#endif
            if (reuse_results) {
                dma->commands[0]=UINT32_C(0xf140);
                ++count; /* Cached START command. */
            } else write_command(dma,&count,TPU_CONTROL,1);
            if (tiny3tpu_dma_submit(dma,count) || wait_done(dma)) return -1;
            if (!reuse_results) result_count=result_commands(reader,row0,col0,m,n);
            if (tiny3tpu_dma_submit(reader,result_count)) {
                dma->poisoned=reader->poisoned;
                return -1;
            }
            uint32_t result=0;
            for (uint32_t core=0;core<2;++core) for (uint32_t row=0;row<4 && row0+row<m;++row)
                for (uint32_t col=0;col<4 && col0+col<n;++col) {
                    const uint32_t lo=reader->responses[result+5];
                    sums[row][col]+=lo<=INT32_MAX ? (int64_t)lo : (int64_t)lo-INT64_C(4294967296);
                    result+=6;
                }
            inner0 += k-inner0<8 ? k-inner0 : 8;
        }
        for (uint32_t row=0;row<4 && row0+row<m;++row) for (uint32_t col=0;col<4 && col0+col<n;++col) {
            if (sums[row][col]<INT32_MIN || sums[row][col]>INT32_MAX) return -1;
            output[(size_t)(row0+row)*n+col0+col]=(int32_t)sums[row][col];
        }
    }
    return 0;
}
