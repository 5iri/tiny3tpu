/* 1216 KiB unified BRAM; 16 KiB reserved stack. 480x270 renderer target. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 1216K }
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > RAM
    .data : { *(.data*) *(.sdata*) } > RAM
    . = ALIGN(16);
    __global_pointer$ = . + 0x800;
    .bss (NOLOAD) : { . = ALIGN(16); __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(16); __bss_end = .; } > RAM
    _stack_top = ORIGIN(RAM) + LENGTH(RAM);
    _stack_size = 16384;
    ASSERT(__bss_end + _stack_size <= _stack_top, "insufficient renderer stack space")
}
