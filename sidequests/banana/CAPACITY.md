# Banana mesh capacity in simulation

The largest tested mesh is **590 vertices / 1,181 nondegenerate triangles**.
It passes the production CPU and UDP peripheral simulation for a full rotation,
and a separate test through two actual LiteEth stacks connected by digital GMII.
This establishes a capacity boundary for the current four-application, 64 KiB
firmware image. It does not establish the KC705's absolute hardware capacity.

All stress builds are separate from the existing 204-vertex / 407-triangle demo.
The experimental firmware changes only the reply-buffer bound; the largest image
also uses `-Os`. The live viewer still uses its original mesh and protocol limits.

## Fresh update latency

Each row below checks three fresh updates and duplicate replay through both MACs,
ARP, IPv4, UDP, the packet peripheral, and the real VexRiscv firmware. System and
GMII clocks are 100 MHz and 125 MHz. Rates are reciprocals of mean fresh-request
latency; duplicate replies are excluded.

| Triangles | Vertices | Compiler | Reply | Mean round trip | Update-rate equivalent |
| ---: | ---: | --- | --- | ---: | ---: |
| 407 | 204 | O2 | Raw | 4.148 ms | 241/s |
| 675 | 338 | O2 | Raw | 6.507 ms | 154/s |
| 962 | 476 | O2 | Compact | 11.649 ms | 86/s |
| **1,181** | **590** | **Os** | **Compact** | **14.528 ms** | **69/s** |

These are digital simulation results. Analog PHY, cable, switch, host NIC/OS,
Python networking, rendering, and browser delivery are excluded. No board was
programmed. Physical Ethernet timing qualification remains outstanding.

The 1,181-triangle image also passed **110 consecutive fresh frames**, including
angle wraparound, at the UDP stream boundary. All **194,810 output words** matched
the native reference and independently advanced JAX execution bit for bit.
Mean latency over the full rotation was 14.723 ms (range 14.522–14.839 ms).
There were no compact fallbacks; duplicate requests replayed without advancing
state. The full-MAC test and full-rotation test have different scope and pose sets.

## Limits found

The raw response is `32 + 12 * vertices` bytes. The 4,096-byte application-message
limit therefore permits at most 338 vertices; the tested 675-triangle mesh uses
4,088 bytes and three UDP datagrams. Larger tested meshes use the existing
lossless compact representation, `44 + 6 * vertices` bytes. Its wire-only limit
is 675 vertices, but this firmware runs out of RAM sooner.

| Configuration | Successful build | Static allocation | Spare after 4 KiB stack | Next failed mesh |
| --- | --- | ---: | ---: | --- |
| O2 | 480 vertices / 961 triangles | 61,356 B | 84 B | 483 vertices / 967 triangles |
| Os | 590 vertices / 1,181 triangles | 61,436 B | **4 B** | 594 vertices / 1,190 triangles |

The O2 476-vertex mesh has 962 faces, one more than the 480-vertex mesh because its
clustering grid differs. Triangle count is not a fixed multiple of vertex count.
All meshes in these boundary comparisons have zero quantized zero-area faces.
The failed builds trip the real linker stack reservation; the study does not
shrink the stack or enlarge RAM. Runtime peak stack usage is not measured.
The 590-vertex build has **4,100 bytes total remaining**, including its reserved
4 KiB stack. It is a capacity experiment with almost no margin for further code.

The automatic compiler policy selects CPU execution for this narrow 3-by-3
transform: the verified banana backend-call count is zero. More TPU cores alone
would not change this execution path. The 100 us fresh-result target is unmet.

A controlled speed comparison uses the same 407-triangle mesh, identical
generated headers, and the same three raw-response poses through full GMII:

| Compiler | Mean round trip | Mean compute | Static allocation |
| --- | ---: | ---: | ---: |
| O2 | 4.148 ms | 3.811 ms | 45,732 B |
| Os | 3.481 ms | 3.011 ms | 40,124 B |
| O3 | **3.124 ms** | **2.809 ms** | 52,692 B |

O3 reduces this mesh's simulated round trip by about 25%, but its larger code
leaves less room for geometry. Os supports the largest tested mesh. The production
defaults remain unchanged; these are separate benchmark images.

## Host rendering

The unchanged Python renderer was also measured on the local Apple M4. Rendering,
PNG, and base64 take roughly 8 ms median at 407 triangles, 12 ms at 675, 17 ms at
962, and **20.01 ms at 1,181**. Each boundary mesh used 240 synthetic full-rotation
poses; every PNG decoded successfully. These inputs are renderer fixtures,
separate from the verified RTL output stream. OS and background workload affect
the tails; raw samples, environment, and repeat runs are retained in the evidence.

The maximum mesh's renderer alone exceeds a 60 Hz frame budget. Actual display
rate also includes JSON, HTTP and browser work. Acquisition and rendering are
separate stages, so these measurements are not a measured end-to-end frame rate.

The viewer needs a mesh-identity/scale/dimension contract before using the larger
meshes: raising its current 613-word check alone would draw the wrong face table.
Per-face NumPy calls dominate the current rendering profile. Batched normals,
depths and lighting, or a browser renderer with a depth buffer, are useful next
experiments. The existing average-depth painter order is approximate visibility.

## Reproduce

Requires the existing JAX/compiler environment, RISC-V GCC and Verilator, the
exported `build-showcase` artifacts, and the Ethernet dependencies described in
[the Ethernet guide](../../hardware/kc705_ethernet/README.md).

```sh
mkdir -p build-banana-capacity/source
curl -L https://raw.githubusercontent.com/SRA-VJTI/jaxsim/c0a097bba1c6db10cac7b359fbac11cfedc48c6b/examples/sampledata/banana.obj \
  -o build-banana-capacity/source/banana.obj

# Coarse O2 sweep, including expected RAM failures.
.venv/bin/python tests/profile_banana_capacity.py \
  --mesh-source build-banana-capacity/source/banana.obj \
  --out build-banana-capacity/sweep

# Largest tested mesh and the next RAM failure.
.venv/bin/python tests/profile_banana_capacity.py \
  --mesh-source build-banana-capacity/source/banana.obj \
  --optimization Os --grids 15x12x13 12x16x13 14x15x12 \
  --build-only --out build-banana-capacity/Os-boundaries

.venv/bin/python tests/test_udp_soc.py \
  --board build-banana-capacity/Os-boundaries/grid-12x16x13/board \
  --out build-banana-capacity/Os590-full-mac \
  --banana-only --banana-format compact --banana-frames 3 --with-mac

.venv/bin/python tests/test_udp_soc.py \
  --board build-banana-capacity/Os-boundaries/grid-12x16x13/board \
  --out build-banana-capacity/Os590-rotation \
  --banana-only --banana-format compact --banana-frames 110

.venv/bin/python tests/check_banana_capacity_jax.py \
  --mesh build-banana-capacity/Os-boundaries/grid-12x16x13/mesh.npz \
  --metadata build-banana-capacity/Os-boundaries/grid-12x16x13/mesh.json \
  --simulation build-banana-capacity/Os590-rotation/report.json \
  --out build-banana-capacity/Os590-rotation/jax-comparison.json
```

The sweep validates the pinned mesh hash, exports the same banana workload at
each size, checks native/JAX output, retains all four application modes, and
records real link failures. The simulation tests exact outputs, counts,
checksums, consecutive state, and duplicate replay. It does not modify the
production firmware, default mesh, or viewer. The refactored exporter produces
the exact original baseline firmware hex.

Machine-readable results, source fingerprints, and report paths are in
[capacity_evidence.json](capacity_evidence.json). Larger meshes will require
changes to memory allocation and response handling. Reducing fresh-result
latency requires addressing CPU transforms and compact encoding as well as the
host renderer.
