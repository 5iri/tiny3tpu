# tiny3tpu

`tiny3tpu` is me trying to make a stupidly small TPU-ish thing do real work on an FPGA and, against reason, it actually runs quantized MNIST end-to-end on hardware.

The whole point here is simple: take a hand-drawn or scripted MNIST digit, shove it through a tiny hardware stack I built, and get a prediction back without pretending this is some giant polished accelerator project.

This repo is the current pile of parts that makes that happen:

- cached quantized MNIST model upload and inference
- a draw-and-infer MNIST demo over the same accelerator protocol
- blocked `16x16` int8 GEMM on hardware
- UART and UDP request/response transport

The two writeups about this repo are:

- [Tiny TPU in a Week](https://5iri.me/blog/tiny-tpu-week)
- [Update: tiny tpu is now bigger!](https://5iri.me/blog/tiny-tpu-is-now-bigger)

![MNIST draw-and-infer demo running on the current stack](https://5iri.me/markdown_files/posts/assets/tiny-tpu-is-now-bigger/mnist-draw-cached-4layer.png)
![UDP + cached-model MNIST results from the current stack](https://5iri.me/markdown_files/posts/assets/tiny-tpu-is-now-bigger/udp-summary-20-samples.png)

## What is working here

The experimental StableHLO system compiler accepts portable
StableHLO or MLIR text and generates CPU code plus TPU calls. JAX is one frontend;
cloth is a validation example. The linked guide records supported operations,
explicit approximation options, and native/RTL verification results.

The experimental Rocket RV64GC backend adds
FP32/FP64 arithmetic alongside the int8 TPU in RTL. Its physical boot attempt
did not respond, and work on it is stopped. The active cloth demo uses VexRiscv
at 100 MHz; the linked record preserves the experiment's validation and failure.

The next bring-up milestone for the post is DDR3 by itself with a hardware-only
test engine. That isolated target contains no
CPU or accelerator; the remaining connections will be added one at a time after
repeatable physical memory tests pass. Its simulation status is separate from
the existing working accelerator setup below.

An UberDDR3 hardware-only trial now evaluates
the same 100 MHz controller target using only open-source tools. Its validation
and timing results are recorded separately from the LiteDRAM implementation.

The thing that is actually alive right now is cached MNIST inference backed by a firmware-controlled `16x16` GEMM engine.

- The firmware in [firmware.c](firmware.c) drives a memory-mapped systolic core through pulse-based control registers.
- Host tools send binary packets for model upload, inference, and raw GEMM over UART or UDP.
- Quantized MNIST MLPs can be exported from PyTorch, cached on the board, and executed layer-by-layer using the same tiled GEMM engine.

The RTL under [multi-core](multi-core) goes wider and gets more experimental, but the checked-in firmware is still the practical, battle-tested path for the setup above.

## Dataflow at a glance

```text
Python scripts yelling at the board
    |
    |  MAT1 / MOD1 / MCH1 / INF1
    v
UART or UDP transport
    |
    v
firmware doing all the annoying real work
    |
    |  stage tiles, schedule cores, cache models in DDR
    v
tiny systolic array pretending to be much bigger than it is
    |
    |  blocked int8 GEMM / matvec
    v
prediction / matrix result comes back out
    |
    |  RSP1 / ACK1 / PRD1
    v
host checks if the whole stunt actually worked
```

The protocol currently includes:

- `MAT1` / `RSP1` for raw GEMM
- `MOD1` and `MCH1` for model upload
- `INF1` / `PRD1` for cached-model inference

The v1 compiler model container uses a zero-scratch contract for the currently
supported host operations: `scratch_offset` and `scratch_bytes` are both zero.
Scratch storage cannot alias the activation arena until a future runtime ABI
defines an independent scratch region.

## Running the host tools

The C++ compiler and portable C runtime can be built and tested locally:

```bash
cmake -S . -B build -DCMAKE_C_STANDARD=11 -DCMAKE_C_EXTENSIONS=OFF \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build -j2
ctest --test-dir build --output-on-failure
```

The JAX test uses the selected Python environment and compares exported matmul
and bias models against both the C++ reference executor and the C runtime.
JAX must be installed in that environment. This verifies host execution; it
does not program an FPGA. The default RTL configuration is two 4×4 cores;
the firmware's 16×16 GEMM is a tiled logical operation.

With Verilator installed, `jax_fpga_sim` runs the exported models through the
C runtime and portable MMIO backend against simulated AXI RTL. It requires
actual accelerator launches and compares outputs to JAX. Icarus adds AXI bus
protocol tests; Yosys adds structural synthesis checks. These tools are
detected at configure time. The firmware compile checks use test-only BSP
declarations and are not board binaries.

The generic firmware path links `src/runtime.c`,
`src/firmware_runtime_adapter.c`, and `src/mmio_backend.c`, and defines
`TINY3TPU_ENABLE_GENERIC_RUNTIME`. Board-specific deployment still needs the
processor/BSP, memory map, clock/reset integration, constraints, bitstream,
and physical verification. See the AXI register map.

See the generic firmware adapter for the
model upload and execution protocol and board integration requirements.

These scripts assume the FPGA is already programmed and the matching firmware is running. If the board is not alive, none of this becomes magically convenient.

Install Python dependencies with:

```bash
pip install -r requirements.txt
```

The host/demo scripts currently depend on:

- `pyserial`
- `pygame`
- `torch`
- `torchvision`
- `numpy`

Examples:

```bash
# Raw 16x16 GEMM check over UART
python3 pyfiles/uart_matrix_host.py --port /dev/ttyUSB1

# Raw 16x16 GEMM check over UDP
python3 pyfiles/uart_matrix_host.py --udp-host 192.168.1.77

# Upload cached model and run MNIST inference samples
python3 pyfiles/mnist_infer_uart.py --udp-host 192.168.1.77 --count 20

# Interactive draw-and-infer demo
python3 pyfiles/mnist_draw_uart.py --udp-host 192.168.1.77
```

If you want to train/export a new quantized MNIST model:

```bash
python3 pyfiles/train_mnist_hw.py --epochs 8 --export mnist_int8_4layer.json
```

## Synapse32 AXI-Stream transport

The optional Synapse32 mailbox and AXI-Stream register-command bridge are
documented in docs_synapse32_stream.md. Tests include
RV32 firmware executing on the actual Synapse32 CPU RTL and a JAX-to-TPU RTL
transport path. This is not yet a KC705 CPU bitstream or physical-board inference.

The open-source KC705 DDR bring-up adds synchronous
boot RAM, a variable-latency CPU memory sequencer, and a LiteDRAM-based board
target with C calibration and DDR-backed TPU self-test firmware. Hardware
qualification is tracked separately from the passing CPU/DRAM-model simulation.
