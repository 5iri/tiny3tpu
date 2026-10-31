/* Simulation/bring-up image: configurable unified logical RAM (default 64 KiB). */
OUTPUT_ARCH(riscv)
ENTRY(_start)
_ram_size = DEFINED(_ram_size) ? _ram_size : 65536;
_stack_size = DEFINED(_stack_size) ? _stack_size : 4096;
MEMORY { RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 512K }
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > RAM
    .data : { *(.data*) *(.sdata*) } > RAM
    . = ALIGN(4);
    __global_pointer$ = . + 0x800;
    /* Startup clears words; align the symbol even when .data is empty. */
    .bss (NOLOAD) : { . = ALIGN(4); __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); __bss_end = .; } > RAM
    _stack_top = ORIGIN(RAM) + _ram_size;
    ASSERT(__bss_end + _stack_size <= _stack_top, "insufficient stack space")
}
