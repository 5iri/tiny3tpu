#ifndef TINY3TPU_TEST_XIL_IO_H
#define TINY3TPU_TEST_XIL_IO_H
/* Compile-only declarations. These are NOT a functional or deployable BSP. */
#include <stdint.h>
typedef uint8_t u8;
typedef int8_t s8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int32_t s32;
typedef uint64_t u64;
typedef int64_t s64;
void Xil_Out32(uintptr_t address, u32 value);
u32 Xil_In32(uintptr_t address);
void outbyte(char value);
char inbyte(void);
#endif
