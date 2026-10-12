# Banana straight to HDMI

The KC705 runs the whole display demo: a compiled JAX program, a RISC-V CPU, two small TPUs, a triangle renderer and HDMI output. The host is only needed to build and load the image.

<a href="https://x.com/lazybanananann/status/2109297764739998109"><img src="../../media/board-demos/hdmi-board.gif" width="320" alt="Physical KC705 driving a monitor with the banana demo"></a>

[Original physical-board video](../../media/board-demos/hdmi-board.mp4) · [Post by @lazybanananann](https://x.com/lazybanananann/status/2109297764739998109)

## What runs where

1. JAX exports the rotation program on the development computer.
2. The compiler turns it into a freestanding RISC-V program.
3. VexRiscv computes the angle and rotation matrix. Two 4×4 int8 TPUs transform the mesh.
4. The CPU sends the transformed vertices to the hardware renderer.
5. The renderer draws into a back buffer. HDMI switches to it between frames.

The image has **3,442 vertices and 6,950 triangles**, rendered at **640×480**. CPU and video logic run at **25.2 MHz**. The image uses **256 KiB of CPU RAM** and separate on-chip display memory. It needs no DDR.

The renderer uses simple lighting and integer geometry. It does not implement a full graphics API, textures, perspective-correct depth or antialiasing.

![HDMI pixels captured from RTL simulation](../../media/board-demos/hdmi-rtl.png)

*This clean pixel image is a simulation capture. The video above is physical footage.*

## Build

From the repository root, install the compiler dependencies and use a Python environment with JAX and NumPy. You also need `riscv64-unknown-elf-gcc`, Verilator, Icarus Verilog, Yosys, nextpnr-xilinx and openXC7. Place the [Synapse32 checkout](https://github.com/5iri/synapse32) beside this repository; the CPU uses its UART RTL.

```sh
.venv/bin/python hardware/kc705_hdmi/cpu/prepare.py --out build-hdmi/firmware

.venv/bin/python hardware/kc705_hdmi/tests/test_cpu.py \
  --firmware build-hdmi/firmware --full-rotation --out build-hdmi/cpu-check
python3 hardware/kc705_hdmi/tests/test_mmio.py --out build-hdmi/mmio-check
python3 hardware/kc705_hdmi/tb/test_init.py --out build-hdmi/i2c-check

python3 hardware/kc705_hdmi/build.py bitstream --cpu \
  --firmware build-hdmi/firmware --out build-hdmi/board \
  --yosys /path/to/yosys --nextpnr /path/to/nextpnr-xilinx \
  --chipdb /path/to/xc7k325tffg900-2.bin \
  --db-root /path/to/prjxray-db/kintex7 --tools /path/to/openxc7/bin
```

The hardware build starts with fresh synthesis and checks source hashes, modeled route timing, and a bitstream configuration-frame round trip. It does not program the board.

Connect power, USB-JTAG and an HDMI monitor to P6, then load volatile SRAM:

```sh
openFPGALoader -b kc705 --write-sram build-hdmi/board/soc.bit
```

Use `--ftdi-serial YOUR_ADAPTER_SERIAL` if multiple JTAG adapters are connected. This command does not write configuration flash.

## Controls

| Control | Action |
| --- | --- |
| Center button | Pause or resume |
| North button | Increase rotation speed |
| SW11 position 3, off → on | Decrease speed |
| SW11 position 2 on / east button held | Backward / forward |
| SW11 position 4 | Diagnostic color bars |
| CPU reset button | Reset CPU and display |

Leave SW11 position 2 off for normal forward rotation. South and west buttons are unused. LEDs 0 and 1 show clock lock and HDMI setup; LED 2 shows an initialization or CPU error; LED 3 means an image is available.

## What was verified

The saved full-rotation test executes the real CPU firmware, both TPU cores, vertex uploads and the renderer. It checks all 256 angles and the wrap to angle zero, including **2,664,108 raw TPU results**, **884,594 uploaded vertices**, and **4,915,200 HDMI pixels**. New frames arrive every 840,000 cycles in that simulation: **30 fps**, with **60 Hz HDMI refresh**.

The board image was loaded successfully on 2026-10-11. The linked physical footage shows the same 6,950-triangle / 3,442-vertex display. An earlier physical test also confirmed correct color bars and a yellow banana. Camera footage is visual evidence, not a frame-rate measurement.

- [Board load record](../../media/board-demos/evidence/hdmi-board-load.json)
- [Earlier physical color test](../../media/board-demos/evidence/hdmi-color-board.json)
- [Full-rotation simulation](../../media/board-demos/evidence/hdmi-rtl.json)
- [Implementation report](../../media/board-demos/evidence/hdmi-implementation.json) and [bitstream export check](../../media/board-demos/evidence/hdmi-export.json)
- [ADV7511 register details](ADV7511_REGISTERS.md)

The routed internal model passed the 25.2 MHz target. Full external HDMI setup/hold timing and monitor compatibility have not been qualified. The saved image hash is `a15dc7adc29f065cd6d2f67cf975accc07433d6c92fedfcd11e7a9ee32fc0098`.

The mesh is derived from [jaxsim's banana](https://github.com/SRA-VJTI/jaxsim/blob/c0a097bba1c6db10cac7b359fbac11cfedc48c6b/examples/sampledata/banana.obj). [Mesh metadata](assets/mesh.json) records the source and reduction; [mesh_assets.py](tools/mesh_assets.py) regenerates the ROM data. The CPU checks its first set of transformed coordinates against JAX before submitting an image.
