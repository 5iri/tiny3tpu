/* Simulation/bring-up image: 64 KiB unified logical RAM, not a KC705 BSP. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 64K }
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > RAM
    .data : { *(.data*) *(.sdata*) } > RAM
    . = ALIGN(4);
    __global_pointer$ = . + 0x800;
    /* Startup clears words; align the symbol even when .data is empty. */
    .bss (NOLOAD) : { . = ALIGN(4); __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); __bss_end = .; } > RAM
    _stack_top = ORIGIN(RAM) + LENGTH(RAM);
    ASSERT(__bss_end + 4096 <= _stack_top, "insufficient stack space")
}
