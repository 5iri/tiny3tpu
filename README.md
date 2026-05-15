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

The thing that is actually alive right now is cached MNIST inference backed by a firmware-controlled `16x16` GEMM engine.

- The firmware in [firmware.c](/Users/siriboi/github/tiny3tpu/firmware.c) drives a memory-mapped systolic core through pulse-based control registers.
- Host tools send binary packets for model upload, inference, and raw GEMM over UART or UDP.
- Quantized MNIST MLPs can be exported from PyTorch, cached on the board, and executed layer-by-layer using the same tiled GEMM engine.

The RTL under [multi-core](/Users/siriboi/github/tiny3tpu/multi-core) goes wider and gets more experimental, but the checked-in firmware is still the practical, battle-tested path for the setup above.

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

## Running the host tools

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
