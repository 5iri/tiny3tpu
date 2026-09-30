.section .text.start,"ax",@progbits
.globl _start
_start:
    lui t0, 0x20002
    sw zero, 0(t0)
    j _start
