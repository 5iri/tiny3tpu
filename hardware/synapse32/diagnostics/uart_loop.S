/* Stage 1: boot RAM + CPU + UART only. No stack, DDR, or function calls. */
.section .text.start,"ax",@progbits
.globl _start
_start:
    lui t0, 0x20000
    li t1, 0x83
    sw t1, 12(t0)
    li t1, 100
    sw t1, 0(t0)
    li t1, 3
    sw t1, 4(t0)
    sw t1, 12(t0)
    li t1, 7
    sw t1, 8(t0)
    li t2, 85
1:  lw t1, 20(t0)
    andi t1, t1, 32
    beqz t1, 1b
    sw t2, 0(t0)
    j 1b
