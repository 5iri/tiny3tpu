# Multiply between existing CPU clock edges

The original sequencer leaves at least four system rising edges between enabled
CPU rising edges. This experiment uses those existing intervals for multiplication:

1. At CPU edge +1, capture the forwarded operands and signed upper halves.
2. At +2, register four 16/17-bit partial products.
3. At +3, combine them into the selected low/high result.
4. At the next enabled CPU edge (+4 or later), consume the result normally.

There is no multiply busy state or added CPU stall. The remaining ALU operations,
branches, exceptions, addresses and operand outputs stay combinational. This is
necessary because the sequencer samples post-CPU-edge memory outputs at +1.
The iterative divider and its architectural cycle count are unchanged.

`SYSTEM_MUL=0` defaults to the previous shared combinational multiplier, supporting
continuously clocked standalone CPU tests. `SYSTEM_MUL=1` requires a free-running
`system_clk` related to the gated CPU clock and the four-edge minimum gap. It is
incompatible with a faster CPU stepping sequencer unless that contract is revised.
No multicycle or false-path timing exception is introduced: both clocks still
target 100 MHz and cross-clock paths must also be checked.

`SYNAPSE32_SYSTEM_MUL_ASSERT` compares the ALU product at every enabled CPU MUL
edge against the current unregistered forwarded operands. The unit test compares
100,389 pipelined products, including mixed signedness, corner values and reset.
The fixed MUL benchmark preserves all instruction/store/writeback traces:
4,007 instructions / 4,118 enabled edges = 0.973045 IPC in both clock modes.
The DMA system test preserves 221,485 instructions, 287,684 CPU edges, 0.769890
IPC and 1,481,754 system cycles, including all 35 checked TPU results.

```sh
python3 hardware/synapse32/experiments/system-mul/run.py verify --out build-sysmul-new
python3 hardware/synapse32/experiments/dma/run.py system --out build-dma-sysmul-new \
  --cpu-overlay-dir build-sysmul-new/overlay --system-mul
python3 hardware/synapse32/experiments/dma/run.py stress --out build-dma-sysmul-stress-new \
  --cpu-overlay-dir build-sysmul-new/overlay --system-mul
python3 hardware/synapse32/experiments/dma/run.py synth --out build-dma-sysmul-new \
  --cpu-overlay-dir build-sysmul-new/overlay --system-mul
python3 hardware/synapse32/experiments/dma/run.py route --out build-dma-sysmul-new \
  --cpu-overlay-dir build-sysmul-new/overlay --system-mul
```

Board synthesis elaborates `SYSTEM_MUL=1` in Slang before reading the board
wrapper; simulation applies the same parameter at the CPU instance. This remains
an isolated experiment. Timing closure and hardware validation are not implied
by simulation success.

The seed-4 DMA board route in `build-ddr-dma-system-mul/board` reaches 55.95 MHz
CPU / 59.29 MHz system, versus 47.62 / 59.07 for the shared combinational MUL
DMA baseline. Both 100 MHz targets fail. The CPU-to-system path is 10.53 ns
(also over its 10 ns budget); system-to-CPU is 7.01 ns. The unsupported DCI
constraint warning remains. This candidate has not been promoted.
