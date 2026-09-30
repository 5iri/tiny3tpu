#ifndef SYNAPSE32_BAREMETAL_SYSTEM_H
#define SYNAPSE32_BAREMETAL_SYSTEM_H
#include <stdint.h>
#define CONFIG_CPU_NOP "nop"
/* This first SoC has no caches or MMU. */
static inline void flush_cpu_dcache(void) { __asm__ volatile("fence iorw, iorw" ::: "memory"); }
static inline void flush_cpu_icache(void) { __asm__ volatile("fence.i" ::: "memory"); }
static inline void flush_l2_cache(void) { flush_cpu_dcache(); }
#endif
