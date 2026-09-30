# Two-entry native DDR write buffer

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

The current generator inherits corrected WRITE-DRAIN ordering and passes all
22 adapter tests in `build-ddr-write-buffer`, including scheduled native writes.
Historical 21-test results below predate this strict check.

This builds on `dram-write-capture` and changes only the completed wide-word
FIFO from depth one (an elastic pipeline register) to depth two. The depth-two
FIFO's input-ready signal depends on its occupancy, breaking the combinational
path from native DDR write-ready through the wide converter's capture enables.
The upstream converter still assembles complete words before the native write
command is issued. Word ordering and byte masks remain the adapter's contract.

The installed LiteDRAM/LiteX packages are unchanged. The generator applies the
candidate in-process and saves source/hash evidence, including the inherited
command FIFO and write-capture patches. It affects the CPU and DMA native
32-to-512 converters in the board build.

```sh
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-write-buffer/verify.py \
  --upstream /tmp/tiny3tpu-litedram-2024.12-tests --out build-ddr-write-buffer
```

All 21 adapter tests pass, including actual 32-to-512 traffic with masked
writes, dependent same-word reads, gaps, flushes and downstream backpressure.
This is simulation validation of the changed FIFO depth; the inherited
write-capture edit separately passes its ownership induction proof.

Enable `dma/run.py --dram-write-buffer`; this includes write capture and command
buffering. Synthesis checks the passing source hashes. Physical frontend
latency/contention are absent from the behavioral CPU/DMA memory model, so its
cycle counts cannot quantify this FIFO-depth change. Board routing is required
before claiming a frequency improvement. Defaults remain unchanged.
