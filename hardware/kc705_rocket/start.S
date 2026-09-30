.section .text.start,"ax",@progbits
.globl _start
_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la sp, _stack_top
    la t0, trap
    csrw mtvec, t0
    /* Enable F/D register state before the first floating-point instruction. */
    li t0, 0x6000
    csrs mstatus, t0
    csrw fcsr, zero
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0, t1, 2f
    sw zero, 0(t0)
    addi t0, t0, 4
    j 1b
2:  call main
    li t0, 0x20002000
    sw a0, 0(t0)
3:  j 3b
.balign 4
trap:
    csrr t1, mcause
    li t2, 0x40000000
    or t1, t1, t2
    li t0, 0x20002004
    csrr t2, mepc
    sw t2, 0(t0)
    csrr t2, mtval
    sw t2, 0(t0)
    li t0, 0x20002000
    sw t1, 0(t0)
4:  j 4b
