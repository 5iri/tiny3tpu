# Synapse32 stream transport

This implementation adds a synthesizable command transport and a bare-metal
CPU simulation. It does **not** yet provide a KC705 CPU bitstream, physical UART
inference, DDR integration, or timing closure. No Synapse32 source is modified.

The control path is:

```text
Synapse32 aligned LW/SW
  -> fixed-latency MMIO mailbox at 0x20001000
  -> two-beat AXI-Stream request
  -> AXI4-Lite transaction
  -> existing two-core 4x4 TPU
  -> two-beat AXI-Stream response
  -> sticky mailbox result
```

This is a **register-command stream**, not a tensor DMA engine. It deliberately
reuses the existing operand/result registers and the C tiling backend. Matrix
shapes, T3M1 model ABI, quantization rules, and the two 4x4 cores are unchanged.
Polling and per-register packet overhead prioritize first bring-up over maximum
bandwidth. Bulk tensor streaming can be added as a separate versioned protocol.

## RTL entry points

- `multi-core/synapse32_tpu_mmio.sv`: native CPU port with full-address decode,
  load/store fault gating, and read/write hit outputs for the board RAM mux.
- `multi-core/synapse32_tpu_peripheral.sv`: local 32-byte peripheral, combining
  the mailbox and accelerator stream wrapper.
- `multi-core/synapse32_axis_mailbox.sv`: CPU staging/result registers.
- `multi-core/tiny3tpu_axis.sv`: standalone AXIS accelerator wrapper.
- `multi-core/tiny3tpu_axis_bridge.sv`: standalone AXIS-to-AXI-Lite bridge.

All blocks must share one clock and coordinated reset. There is no clock-domain
crossing logic. Reset must cover mailbox, bridge, and accelerator together, for
at least a rising clock edge; synchronize reset release in the board wrapper.
Do not reset just the bridge while an AXI target retains an old transaction.

The stream obeys the TVALID/TREADY handshake: transfers happen only when both
are asserted, and valid data/sidebands are held while backpressured. See the
[Arm AXI-Stream specification](https://documentation-service.arm.com/static/64819f1516f0f201aa6b963c).

## Command and response format

Each request is exactly two 32-bit beats, each with `TKEEP=0xf`:

| Beat | TDATA | TLAST |
| --- | --- | --- |
| 0 | Header described below | 0 |
| 1 | Write data; ignored for reads (driver sends zero) | 1 |

Header bits:

| Bits | Meaning |
| --- | --- |
| 31:16 | Reserved, must be zero |
| 15:12 | AXI-Lite WSTRB; ignored on reads |
| 11:9 | Reserved, must be zero |
| 8 | 1 = write, 0 = read |
| 7:0 | Accelerator register byte offset, **not** CPU mailbox offset |

Each response is two beats with `TKEEP=0xf`. Beat 0 has `TLAST=0`, the AXI
response code in bits 1:0, and zero in all other bits. Beat 1 has `TLAST=1` and
contains read data, or zero for writes. Codes are OKAY=0, SLVERR=2, DECERR=3.
The accelerator rejects unmapped/unaligned register offsets through its existing
AXI-Lite error response. This is distinct from a malformed stream packet.

The bridge validates the whole command before causing any AXI side effect.
Short/bad packets return SLVERR; overlong packets are drained through TLAST,
then return SLVERR. A sender that never finishes a packet requires coordinated
reset to recover. AW and W handshakes are tracked independently. No new command
is accepted until the previous response's final beat has been consumed.

## CPU mailbox map

Reserve `0x20001000..0x2000101f`. UART remains at `0x20000000`.
CPU accesses are aligned 32-bit LW/SW only, with full `cpu_wstrb=0xf` for writes.
The CPU's byte-address-relative SB/SH strobes must not be mistaken for AXI lanes.
Header WSTRB is independent and may request partial accelerator writes.
Atomics are not supported by the software contract.

| Offset | Register | Meaning |
| --- | --- | --- |
| 0x00 | HEADER | Request header staging |
| 0x04 | DATA | Request payload staging |
| 0x08 | CONTROL | Write bit 0 SUBMIT, bit 1 ACK, bit 2 CLEAR_MISUSE |
| 0x0c | STATUS | Bit 0 busy, bit 1 result ready, bit 2 sticky misuse |
| 0x10 | RESP_CODE | Response code |
| 0x14 | RESP_DATA | Response data |

SUBMIT snapshots both staging words. They may then be changed without affecting
the in-flight command. SUBMIT while busy, with an unread result, or with an
invalid header is rejected and raises misuse. ACK clears result-ready but does
not erase response data. ACK is only valid with a completed result. Issue ACK
and SUBMIT as separate writes. A same-cycle result completion does not allow a
busy SUBMIT to replace that result.

Mailbox reads are combinational from registered state: Synapse32 samples the
value in its existing MEM cycle. Unsupported local accesses return zero or
raise sticky misuse rather than silently aliasing a valid register. The native
adapter returns zero for non-LW reads and suppresses faulted accesses.

Malformed response frames are reported as DECERR; overlong frames must be
drained before accepting another command. Missing TLAST can still require a
reset. Mailbox completion means the **register transaction** completed; TPU
compute completion is the separate accelerator STATUS/DONE register.

## Firmware

`include/tiny3tpu_axis_mailbox.h` / `src/axis_mailbox.c` provide a freestanding
C11 driver. Supply ordered, full-word mailbox-local read/write callbacks:

```c
tiny3tpu_axis_mailbox mailbox;
tiny3tpu_axis_mailbox_init(&mailbox, board_user, board_read, board_write, 1000);
tiny3tpu_mmio accelerator = {
    &mailbox,
    tiny3tpu_axis_mailbox_read32,
    tiny3tpu_axis_mailbox_write32,
    1000
};
tiny3tpu_qgemm_backend backend = { &accelerator, tiny3tpu_mmio_qgemm };
```

Use one owner; the driver is not interrupt-reentrant or thread-safe. Poll limits
count register reads, not milliseconds. On timeout, callback failure, or
ambiguous ownership, the driver fails closed (poisoned): later requests cannot
accidentally consume a late old response. `tiny3tpu_axis_mailbox_reset` only
clears the **software** latch; hardware must first be reset or verifiably drained
and acknowledged. Initialization is not a hardware reset either.

`hardware/synapse32/stream_smoke.c` runs the real C MMIO backend, checks a bad
register access, and compares every element of a signed 5x11x7 GEMM. It compiles
for `rv32i_zicsr_zifencei` / ILP32, linking RV32I libgcc arithmetic helpers.
`start.S` initializes gp, stack, and BSS. The linker uses a 64 KiB unified logical
memory in the simulator; initialized data is loaded with the image. Its exit
write at `0x20002000` and result writes at `0x20002004` are **test-harness ports**,
not physical board peripherals. The host independently checks all 35 results.

## Verification

```sh
cmake -S . -B build-stream \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python" \
  -DTINY3TPU_SYNAPSE32_DIR=/path/to/synapse32
cmake --build build-stream -j 4
ctest --test-dir build-stream --output-on-failure -j 3
```

The CPU test is opt-in and requires a separate Synapse32 checkout, Verilator,
`riscv64-unknown-elf-gcc`, and `riscv64-unknown-elf-objcopy`. This implementation
was exercised against local Synapse32 commit
`2372f48bd118629224bd0662b1ca1a999fbb175f` (origin `5iri/synapse32`, upstream
`sra-vjti/synapse32`); compatibility with other revisions is not assumed.

The tests distinguish these evidence levels:

- Unit RTL: stream backpressure, independent AW/W completion, framing, reset,
  mailbox ownership, and native CPU address/fault decode.
- C driver tests: response errors, callback failures, timeout, stale-result
  protection, and direct compatibility with MMIO callbacks.
- C/runtime through mailbox and actual TPU RTL: 16 signed GEMM shapes including
  tails and delayed completion polling.
- JAX export -> C++ compiler -> C runtime -> mailbox -> TPU RTL. This runs the
  runtime on the host; it does not claim the entire JAX model ran on the CPU.
- Actual Synapse32 CPU RTL executing RV32 firmware -> mailbox -> TPU RTL:
  signed 5x11x7 GEMM, with the CPU doing the result comparison itself.
- Yosys structural synthesis checks: not place-and-route or board timing proof.

The CPU fixture supplies combinational memory from C++, not FPGA BRAM. The
Synapse32 build deliberately instantiates `riscv_cpu` directly and excludes its
`rtl/top.v`, avoiding the collision with tiny3tpu's existing `module top`.

## Still required for KC705

Build a board SoC around `riscv_cpu` and `synapse32_tpu_mmio`, with correct
instruction/data memory latency, image initialization, UART, clock/reset, and
KC705 pin constraints. Exclude mailbox hits from RAM accesses and add its read
data to the memory mux. If MMU support is enabled, decode physical addresses and
gate page-faulted accesses; this test runs bare-metal M-mode without the MMU.

The current CPU has no external memory-ready input, so a synchronous BRAM or
DDR controller cannot simply replace the test's combinational memory. Resolve
that timing contract before claiming a board-ready SoC. Then synthesize, route,
check timing/resource use, generate a bitstream, and run UART inference on the
physical KC705. JAX/compiler remain host-side; Synapse32 runs the firmware.
