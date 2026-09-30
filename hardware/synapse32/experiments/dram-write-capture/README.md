# DDR wide-word write capture

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

The current generator inherits the corrected WRITE-DRAIN ordering. Its capture
induction proof and all 22 adapter tests, including scheduled native writes,
pass in `build-ddr-write-capture-final`. Historical 21-test results below
predate the strict native-interface check.

The native 32-to-512 write converter previously gated every lane's capture with
`sink.valid && sink.ready`. The candidate uses `sink.ready`; the lane index and
completion state still advance only on an accepted input. Thus an unfilled lane
can change while input valid is low. An accepted chunk overwrites that lane
before it becomes owned, and a completed output word remains stable during
backpressure. This cuts selection and input-valid logic out of the wide data
register's enable path without adding an interface cycle.

The edit is restricted to the LiteDRAM native upconverter's write datapath. That
path always assembles all chunks of a wide word, inserting zero-strobe fillers
for unrequested chunks. It never asserts the stream converter's early `last`
input. This is **not a general replacement for partial-word stream conversion**:
unused lanes of an early-completed word need a separate validity definition.

`generate.py` applies the edit only in the generator process, together with the
registered command FIFO from `dram-command-buffer`. Installed LiteX/LiteDRAM
files are unchanged. Generated evidence saves both converter sources, adapter
source and hashes. The native read converter and other stream converters keep
their original implementations.

The proof compares the generated 36-to-576 converter (32 data + 4 byte strobes
per chunk) with the original under arbitrary valid/data/ready/first/reset and
`last=0`. It checks control every cycle and all owned lanes, including the entire
payload whenever source valid is asserted. Temporal induction establishes the
invariant. Adapter tests then exercise reads, writes, gaps, partial address
groups, masked strobes and dependent write/read traffic at the board's actual
32-to-512 width.

```sh
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-write-capture/verify.py \
  --upstream /tmp/tiny3tpu-litedram-2024.12-tests --out build-ddr-write-capture-final
```

Use `dma/run.py --dram-write-capture` for board generation; it includes command
buffering. Synthesis checks the passing proof/test source hashes. This board-only
change is absent from the behavioral CPU/DMA memory model, so that model's IPC
and cycle counts cannot measure its effects on physical DDR contention/latency.

The proof passes temporal induction, and all 21 adapter tests pass in
`build-ddr-write-capture-final`. The custom 32-to-512 test covers 97 writes and
97 reads at each of two response-backpressure settings, checks dependent
same-word reads, and compares the full final memory contents.

The seed-4 route in `build-ddr-dma-write-capture/board`, with `system-control`,
`bus-payload` and TX `uart-fifo`, reports **84.28 MHz CPU / 73.06 MHz system**.
System-to-CPU delay is 9.46 ns (passes 10 ns); CPU-to-system delay is 10.96 ns
(fails). Both main clock targets still fail 100 MHz. The unsupported
`get_iobanks`/DCI constraint diagnostic remains; no physical signoff is claimed.
