# StableHLO workload showcase

The banana, synthetic MLP and synthetic causal attention block use the same
StableHLO compiler. JAX exports the functions offline. Generated programs run on
the KC705's 100 MHz VexRiscv, int8 TPU and optional exponential CORDIC peripheral.
The live host performs UART transport and pixel rendering; it imports no JAX and
executes no model or simulation step.

Physical checks on 2026-09-30:

| Program | Board compute | TPU calls | Verified output |
|---|---:|---:|---|
| Quantized MLP | 7.52 ms | 2 | 20 words |
| Attention, software exponential | 52.57 ms | 6 | 64 words |
| Attention, CORDIC exponential | 45.92 ms | 6 | 64 words |
| Banana rotation and camera transform | 29.57 ms | 1 | 613 words including angle |

All output words matched independent native generated C exactly for the checked
requests, including recurrent banana updates. Invalid requests were rejected.
The attention computation is 14.5% faster with CORDIC (1.145× throughput).
These are compute times, excluding UART, pixels and display. The live viewer's
completed-request rate includes inference sampling between banana frames.
Synthetic inference fixtures have seeded weights; these measurements establish
execution, not trained-model accuracy. This does not establish support for all
StableHLO operations or arbitrary JAX programs.

The pretrained TinyStories-1M example is a memory audit, not language inference.
Its pinned configuration requires 3,216,448 bytes for int8 token embeddings
alone: 49.1× the entire current 64 KiB RAM. Weights were not downloaded. Other
weights, quantization metadata, firmware and activations require more storage.
The current image has no DDR runtime; CORDIC cannot solve the storage limit.
Pinned metadata and physical verification are in `media/showcase/evidence`.

## Reproduce

Prepare the reduced banana mesh using `sidequests/banana/render.py` as described
in that directory's README. Then, using a Python environment with JAX, NumPy,
Pillow and pyserial:

```sh
python sidequests/showcase/prepare.py
python sidequests/showcase/build_board.py --out build-showcase/board-lut6
```

Build the no-DDR `vexriscv-lite` board with `tools/kc705_open_build.py`, passing
`--cordic --lut6`, the generated include directory, and
`--firmware-source sidequests/showcase/firmware.c`. Export with
`tools/kc705_export_bitstream.py`, which checks routed timing and frame roundtrip.
Program the resulting image before the physical check; the banana oracle expects
freshly reset resident angle state.

```sh
python sidequests/showcase/uart_sim.py --board build-showcase/board-lut6
python sidequests/showcase/verify_board.py --board build-showcase/board-lut6
python sidequests/showcase/live.py
```

The RTL UART regression covers repeated MLP and both attention modes; the
physical regression additionally checks banana and invalid commands. Open
http://127.0.0.1:8766 for the live viewer. Serial defaults to
`/dev/cu.usbserial-0001` at 921600 baud. Recompute the model memory report with
`model_memory.py --config media/showcase/evidence/config.json --out
build-showcase/pretrained/memory-report.json` and copy the pinned source metadata
there before launching a fresh viewer.
