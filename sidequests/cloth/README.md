# Cloth on the KC705

The board runs the cloth physics on its RISC-V CPU and transforms the geometry on the TPU. The host receives the results over UART and draws the pixels.

<img src="../../media/showcase/gifs/cloth.gif" width="500" alt="Cloth state returned by the physical KC705, played back faster than real time">

The saved run took about 150 ms to compute each tiny 1/7680-second integration step. The CPU has no hardware floating-point unit. The animation is time-compressed and is not a real-time simulation.

The physical regression checked 180 state words and 84 camera coordinates against the native generated-C program for the tested requests. This does not prove long-run agreement with the original JAX trajectory.

## Code

- [compile_program.py](compile_program.py) exports the physics and generates C.
- [compiled_live_firmware.c](compiled_live_firmware.c) runs that program on the board.
- [live.py](live.py) receives board state and draws the host viewer.
- [compare_compiler_accuracy.py](compare_compiler_accuracy.py) compares numerical paths.

Use the Python/JAX environment from the main README, plus Pillow and pyserial. Build and program the matching compiled-cloth firmware before starting the viewer:

```sh
.venv/bin/python sidequests/cloth/compile_program.py --help
.venv/bin/python sidequests/cloth/live.py --compiled --port /dev/ttyUSB1
```

Use [kc705_open_build.py](../../tools/kc705_open_build.py) for the no-DDR VexRiscv image and [kc705_export_bitstream.py](../../tools/kc705_export_bitstream.py) for checked export. The compiled firmware expects the mailbox TPU interface.

[Capture timings](../../media/showcase/gifs/cloth-capture.json) · [Saved physical viewer state](../../media/cloth-thread/board-snapshot.json)
