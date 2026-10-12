# KC705 UART demos

These demos use a 100 MHz VexRiscv CPU, two 4×4 int8 TPUs and 64 KiB of on-chip RAM. JAX exports the programs on the computer. The board computes the results; the computer receives them over UART and draws the viewer.

| Demo | Saved board compute time | Physical check |
| --- | ---: | --- |
| Banana | 29.57 ms | 613 output words, including the angle |
| Small synthetic MLP | 7.52 ms | 20 output words |
| Attention, software exponential | 52.57 ms | 64 output words |
| Attention, CORDIC exponential | 45.92 ms | 64 output words |
| Trained MNIST classifier | About 104 ms | All logits for the first 20 test images |

These are saved physical measurements, excluding UART and drawing. They are not predictions for a new build. The attention and small MLP use synthetic weights; the MNIST classifier uses trained weights. The [main gallery](../../README.md#demos) shows the actual captures.

## Prepare and run

Use the compiler environment from the main README, plus Pillow and pyserial. The build scripts also need the RISC-V toolchain. First prepare the reduced mesh using [the banana guide](../banana/README.md), then:

```sh
.venv/bin/python sidequests/showcase/prepare.py
.venv/bin/python sidequests/showcase/build_board.py --out build-showcase/board
```

The board image must contain the no-DDR VexRiscv runtime and CORDIC peripheral. Build it with [kc705_open_build.py](../../tools/kc705_open_build.py), selecting `--cpu vexriscv-lite --no-ddr --cordic --lut6`, the generated include folder and `--firmware-source sidequests/showcase/firmware.c`. Export it with [kc705_export_bitstream.py](../../tools/kc705_export_bitstream.py) before programming the board. Use each tool's `--help` for local toolchain paths.

After programming and resetting the matching image:

```sh
.venv/bin/python sidequests/showcase/verify_board.py --board build-showcase/board
.venv/bin/python sidequests/showcase/live.py
```

Open the viewer at `http://127.0.0.1:8766`. The default serial device is `/dev/cu.usbserial-0001` at 921600 baud; use the viewer's `--port` option for your device.

The separate classifier path uses [train_classifier.py](train_classifier.py), [classifier_firmware.c](classifier_firmware.c) and [classifier_live.py](classifier_live.py). Saved weights and test inputs are in [media/showcase/evidence/classifier](../../media/showcase/evidence/classifier). Its 92.78% full-test accuracy was measured offline; only the first 20 samples were physically checked.

[Physical checks](../../media/showcase/evidence/physical-check.json) · [GIFs and capture notes](../../media/showcase/gifs/README.md)
