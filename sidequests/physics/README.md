# Live double pendulum

Adapted from SRA-VJTI/jaxsim's `examples/demo_double_pendulum.py` at commit
`c0a097bba1c6db10cac7b359fbac11cfedc48c6b`. Uses its `DoublePendulum.forward`
equations, initial angles, and low-poly sphere mesh.

- Physics: upstream JAX ODE, host CPU, fixed-step RK4 at 240 Hz.
- Parameters: two 1 m rods, two 1 kg masses, gravity 9.81 m/s².
- Sphere camera transforms: physical KC705, two 4×4 TPU cores, no DDR.
- Every int32 coordinate and UART checksum is checked before rendering.
- Rasterization: upstream JAX SoftRenderer on the host, 96×96, enlarged to 512×512.
- Rods and a motion trail: host drawing based on verified sphere coordinates.
- Physics advances according to wall time; display FPS does not change gravity
  or simulation step size. Startup/compilation happens before the simulation clock starts.

This does not execute the nonlinear pendulum ODE on the FPGA. The board image
contains the sphere mesh instead of the banana mesh, so use the matching image.

## Prepare and check

Use the same environment and pinned upstream checkout as the banana sidequest,
plus `h5py` and `tqdm` (imported by upstream utilities):

```sh
python sidequests/physics/prepare.py --jaxsim /path/to/jaxsim
python sidequests/banana/firmware_sim.py --live \
  --vertices build-physics/mesh --out build-physics/rtl
```

The UART regression checks ten consecutive requests. Build the no-DDR board
image with `sidequests/banana/live_firmware.c` and firmware include directory
`build-physics/mesh`, following the existing KC705 build/export/program flow.
The live firmware uses 921600 baud.

## Live window

After loading the sphere image into volatile FPGA SRAM:

```sh
python sidequests/physics/live.py --jaxsim /path/to/jaxsim
python sidequests/banana/window.py \
  --title 'KC705 — Live Double Pendulum / FPS' \
  --heading 'KC705 / DOUBLE PENDULUM' \
  --scope 'JAX physics on host · KC705 TPU sphere transforms · JAX rasterization on host · No DDR'
```

The window shows measured FPS, FPGA/driver time, transport time, rendering time,
simulated time, and energy drift. UART reads wait indefinitely; the last frame
remains visible while waiting. Close the window to close only the viewer.
State and verified frame logs are under `build-physics/live`; the dashboard is
at `http://127.0.0.1:8765`.

The initial integration check measured relative energy drift of 0.0273% over
30 seconds. Halving the step changed the state after two seconds by at most
8.53e-6. These are numerical checks, not a claim of bit-exact trajectories:
double-pendulum motion is chaotic and long-term paths depend on numerical error.

The live board run reached approximately 46 FPS with over 600 consecutive
verified frames. Both sphere transforms together took about 7.1 ms of
FPGA/CPU-driver time; UART transfer and host wait added about 13.4 ms. These
stages overlap host rasterization. The displayed image has 96×96 source pixels.
