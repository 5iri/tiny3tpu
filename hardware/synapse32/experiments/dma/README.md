# Open AXI DMA with RV32IM firmware

See [IPC_AUDIT.md](../IPC_AUDIT.md) for the cycle-by-cycle IPC accounting and
the subsequent command-builder firmware improvement. Earlier native DDR
command-buffer routes require the
[write-scheduling correction](../DDR_NATIVE_WRITE_CORRECTION.md).

This experiment connects the real Synapse32 CPU and two 4×4 TPU cores through
an open AXI DMA engine. Firmware fills command batches in DDR, starts the DMA
through ordinary MMIO stores, and checks response batches after completion.
It uses RV32IM with the existing CSR/FENCE extensions; there are no new CPU
instructions. Existing board and firmware defaults are unchanged.

The MIT-licensed engine is vendored from
[verilog-axi](https://github.com/alexforencich/verilog-axi/tree/516bd5dadc3365b7f9e225d2af8fe0b8d804fe53),
revision `516bd5dadc3365b7f9e225d2af8fe0b8d804fe53`. The license, source URLs and
hashes are in `third_party/verilog-axi`. The engine uses 32-bit AXI and AXIS,
16-beat maximum bursts, one-bit IDs/tags and aligned transfers. The wrapper's
TDM1 register ABI is defined here; it does not implement the AMD DMA register ABI.

## Data path and ownership

`synapse32_axi_dma.sv` validates/snapshots paired read/write descriptors and
starts both directions. `tiny3tpu_dma_batch.sv` splits the transmit stream into
the TPU's two-word command packets and joins its two-word responses into one
receive transfer. Packet counters advance only on ready/valid handshakes.
The wrapper exclusively owns the TPU transport for the batch. A pending legacy
mailbox command or unread mailbox response prevents DMA start.

DONE requires both DMA descriptor statuses, including the final write response.
Response-code and framing errors also fail the batch. DONE remains set until
acknowledged. Configuration writes, START and ACK while busy are rejected without
altering the active transfer. An error or firmware timeout poisons the driver;
buffers remain owned until a coordinated reset of CPU, DMA, transport and memory
interface. A software timeout does not cancel AXI transactions.

Buffers must be disjoint, contiguous, uncached physical DDR memory. This CPU has
no data cache. Fences order CPU buffer accesses and MMIO descriptor operations.
The smoke firmware uses TX `0x40020000`, RX `0x40022000`, capacity 256 commands.
The GEMM backend batches operand loads, waits for accelerator completion through
a separate status batch, and then batches result reads. It handles signed data,
zero-padded tails, 64-bit partial sums and 32-bit output overflow checks.

## TDM1 registers

Base address: `0x20003000`. Registers are 32 bits.

| Offset | Register | Meaning |
| --- | --- | --- |
| 0x00 | TX address | Command buffer physical address |
| 0x04 | RX address | Response buffer physical address |
| 0x08 | Bytes | 8..65528, multiple of eight |
| 0x0c | Control | START bit 0; completion ACK bit 1 |
| 0x10 | Status | BUSY bit 0; DONE bit 1; ERROR bit 2; MISUSE bit 3 |
| 0x14 | Read error | DMA read descriptor error code |
| 0x18 | Write error | DMA write descriptor error code |
| 0x1c | ABI | `0x54444d31` (TDM1) |

TX/RX require four-byte alignment, no overlap, and their complete spans must
fit in `0x40000000..0x7fffffff`. The current driver polls once per batch; the
wrapper's completion IRQ output is available but not wired to the CPU.

## Reproduction and evidence

```sh
python3 hardware/synapse32/experiments/shared-mul/run.py prepare --out build-shared-new
python3 hardware/synapse32/experiments/dma/run.py unit --out build-dma-unit-new
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-new \
  --cpu-overlay-dir build-shared-new/overlay
python3 hardware/synapse32/experiments/dma/run.py stress --out build-dma-stress-new \
  --cpu-overlay-dir build-shared-new/overlay
python3 hardware/synapse32/experiments/dma/run.py synth --out build-dma-new \
  --cpu-overlay-dir build-shared-new/overlay
python3 hardware/synapse32/experiments/dma/run.py route --out build-dma-new \
  --cpu-overlay-dir build-shared-new/overlay
```

The unit test in `build-ddr-dma-unit-final` passes 24 cases with randomized
channel backpressure, 4 KiB boundaries, final-write completion, invalid buffers,
busy misuse, legacy ownership, AXI/TPU errors and reset during active transfers.
The real CPU system test retains the original DDR selftest, legacy mailbox error
probe, CPU reference GEMM and host scoreboard. All 35 signed 5×11×7 GEMM outputs
pass. Five additional shapes pass all 162 outputs in `build-ddr-dma-stress`.

| Same selftest + 5×11×7 workload | Instructions | Enabled CPU edges | CPU IPC | System cycles |
| --- | ---: | ---: | ---: | ---: |
| Original RV32I mailbox | 795,508 | 1,089,919 | 0.729878 | 4,981,249 |
| RV32IM mailbox | 783,455 | 1,066,166 | 0.734834 | 4,883,469 |
| RV32IM DMA | 221,485 | 287,684 | 0.769890 | 1,481,754 |

The DMA version improves measured IPC by 5.48% and reduces simulated system
cycles by 70.25% against the original RV32I workload. These firmware variants
complete the same useful task, but have different instruction streams. A separate
fixed-program CPU benchmark checks hardware changes against identical traces.
The instruction counter records EX completions; these measurements exclude
interrupts and faults and do not establish precise exception retirement.

The memory model shares RAM contents between CPU and DMA and checks AXI bursts
with independent randomized channel delays. It does not model physical DDR
contention, PHY timing or calibration. Cycle counts cover boot, selftest, setup,
GEMM and verification, not isolated TPU throughput or measured board performance.

The original DMA board route in `build-ddr-dma/board` uses 36 DSPs and reaches
47.62 MHz CPU / 59.07 MHz system at seed 4. **Both 100 MHz targets fail.** The
unsupported DCI constraint warning also remains. No bitstream was programmed.
The `system-mul` experiment is an additional opt-in candidate; see its README.

Further isolated CPU candidates are documented in `system-operands`,
`system-alu`, `system-control` and `system-csr`. They use existing system-clock
gaps to preserve enabled-CPU-edge IPC. Optional `--bus-payload`, `--uart-fifo`
and `--dram-write-capture` paths have separate proofs; the last option includes
the command FIFO and is a board-only frontend change. None is promoted by this
runner to the default design.

The corrected DDR adapter and a subsequent routed candidate are documented in
[DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md). Current
firmware IPC accounting and the explicitly deferred branch-prediction option
are in [IPC_AUDIT.md](../IPC_AUDIT.md). Further control-path experiments are
[divider-payload](../divider-payload/README.md) and
[uart-control](../uart-control/README.md); `--uart-control` selects the latter
and includes both UART payload variants.

Ethernet is a future transport extension, documented in
[ETHERNET_EXTENSION.md](../../ETHERNET_EXTENSION.md). It needs a MAC, packet
handling, clock-crossing buffers and an independent Ethernet DMA path before
network traffic can be included in these tests or timing results.
