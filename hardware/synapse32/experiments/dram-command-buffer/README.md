# Registered LiteDRAM conversion commands

> Earlier buffered-DDR timing results below predate a native-write scheduling
> correction and are not valid board candidates. See
> [DDR_NATIVE_WRITE_CORRECTION.md](../DDR_NATIVE_WRITE_CORRECTION.md).

The current generator includes WRITE-DRAIN after write metadata enqueue;
metadata acceptance no longer releases a native write command. The corrected
adapter passes all 22 tests, including scheduled native writes without waiting
for `wdata.valid`, in `build-ddr-command-buffer/unit-512`. Older results below
describe the earlier, insufficient test suite and are retained for history.

The 32-to-512-bit native width converter originally passes its command selection
mask combinationally through a depth-zero FIFO. Full-board timing paths ran from
the Wishbone/AXI frontend state, through that mask and the converter's write-data
control, to distant register enables. The multiplier-only DMA route spent 15.3 ns
of a 16.9 ns system path in routing.

`generate.py` changes that command FIFO to depth one in the generator process.
It saves the original and patched Python source plus their hashes under the
generated board output. It never edits the installed LiteDRAM package. The
experiment currently applies to both CPU and DMA width converters.

Both original and modified converters pass 20 upstream tests from LiteDRAM
2024.12, commit `7cc1e0f03d457230e9099b1635c9f9527499c0ca`, plus the board-width
test in `width512_test.py`. That test checks 194 writes and 194 reads across its
two backpressure cases, including masked writes, word and 4 KiB boundaries,
bursts and same-word write/read dependencies. It checks the entire final memory
image as well as returned data.

The board-width test uses ordered native memory service with randomized delays.
An initial version using the upstream independent read/write memory handlers
failed on both converters because those handlers could let a read overtake a
pending write. The test model was corrected; converter behavior was not changed
to accommodate that failure.

```sh
git clone --depth 1 --branch 2024.12 https://github.com/enjoy-digital/litedram.git /tmp/litedram-tests
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-command-buffer/verify.py \
  --upstream /tmp/litedram-tests --out build-ddr-command-buffer/baseline-512
.venv-ddr-compat/bin/python hardware/synapse32/experiments/dram-command-buffer/verify.py \
  --upstream /tmp/litedram-tests --out build-ddr-command-buffer/unit-512 --buffered
```

Use `--dram-command-buffer` on the DMA experiment's synthesis command to opt in.
The generator retains the original native port widths and DDR/clock settings.
The DMA system-level behavioral memory model does **not** instantiate this
frontend, so its unchanged cycle counts do not measure the extra FIFO's latency.
These converter tests and board synthesis/routing are separate evidence. DDR
PHY, calibration, cross-port contention and physical hardware remain unvalidated.
