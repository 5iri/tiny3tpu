# Generic firmware/runtime seam

`tiny3tpu_firmware_runtime_adapter.c` is a vendor-neutral command seam around
`tiny3tpu_runtime`. It uses fixed caller-provided buffers and does not include
Xilinx, lwIP, or other BSP headers.

## Wire commands

The legacy firmware consumes the four-byte `T3R1` request magic before calling
the adapter. The adapter then reads little-endian fields and emits a `T3S1`
response containing `s32 status`, `u32 value_count`, and optional little-endian
`s32` values.

| Command | Payload after command | Result |
| --- | --- | --- |
| `1` LOAD | `u32 model_bytes`, then T3M1 bytes | status only |
| `2` BIND_INPUT | `u32 tensor_id`, `u32 byte_count`, then input bytes | status only |
| `3` RUN | none | status only |
| `4` READ_OUTPUT | `u32 tensor_id`, `u32 element_count` | status plus values |

The model and input are copied into configured storage before the runtime is
called. LOAD uses a separate staging buffer and only replaces the active model
after validation succeeds, so a failed upload cannot corrupt the previous
model.

## Board port requirements

To enable the optional dispatch in `firmware.c`, compile as C11, define
`TINY3TPU_ENABLE_GENERIC_RUNTIME` and link `src/firmware_runtime_adapter.c`
and `src/runtime.c` plus `src/mmio_backend.c`. The board build must provide the existing firmware's BSP
headers and symbols (`xil_io.h`, `xparameters.h`, UART/time APIs, and any
enabled lwIP headers), plus active/staging model buffers and the data buffers
sized by these macros:

* `TINY3TPU_GENERIC_MODEL_CAPACITY`
* `TINY3TPU_GENERIC_WORKSPACE_CAPACITY`
* `TINY3TPU_GENERIC_INPUT_CAPACITY`
* `TINY3TPU_GENERIC_OUTPUT_CAPACITY`

The current guarded firmware port supplies a callback backed by the existing
portable two-core 4x4 MMIO backend (`tiny3tpu_mmio_qgemm`). It tiles arbitrary
positive M/K/N dimensions and zero-pads partial tiles. The runtime repacks model weights from `[N,K]`
to callback `[K,N]` in caller-owned workspace before invoking it. A different
FPGA port may replace that callback with its own AXI/register implementation;
it must wait for completion and return nonzero on timeout or bus failure. This
AXI wrapper is in `multi-core/tiny3tpu_axi.sv`; see
[the register contract](docs_axi_registers.md). BSP integration, timing closure,
bitstream generation, cache maintenance, and physical board testing remain
board-specific work.

The MMIO backend accepts sticky `STATUS.DONE` as well as a busy-to-idle
transition. This avoids a timeout when CPU polling misses the busy interval.
Reset or an accepted idle START clears DONE in the wrapper.

The generic workspace is aligned for the callback's `int32_t` output. Portable
runtime callers may supply unaligned byte storage; QGEMM then uses software.
The callback computes signed int8 matrix products only. Requantized QGEMM,
convolution, and pooling currently execute in software, so host correctness
does not imply acceleration of those operations on the FPGA.

When the macro is absent, no generic state or dispatch is compiled and the
existing UART `MAT1`, `MOD1`, `MCH1`, and `INF1` behavior is unchanged.
