# StableHLO system compiler

The system compiler consumes **StableHLO MLIR text or a portable StableHLO
artifact**, and emits a C entry point containing CPU loops, planned buffers, and
calls to the existing `tiny3tpu_qgemm_backend`. It has no cloth, mesh, camera,
time-step, or fixed-point simulation-state assumptions. JAX is an optional source
frontend. Hand-written StableHLO uses the same compiler.

This is an initial backend with an explicit supported subset, not complete
StableHLO coverage or a JAX device plugin. `jax.jit` does not automatically dispatch
to the KC705. Compile/export happens on the development machine; emitted programs
need no Python, JAX, or MLIR runtime on the board.

## Pipeline and API

```text
JAX export / another StableHLO producer / hand-written MLIR
                    ↓
MLIR parsing and verification
                    ↓
function/composite decomposition, loop outlining/specialization, constant evaluation
                    ↓
static index-map composition, target legalization and costed affine partitioning
                    ↓
generic elementwise fusion/index views, buffer liveness, C loops, int8 TPU calls
                    ↓
RISC-V firmware + existing CPU/TPU runtime
```

Parsing uses actual MLIR bindings, not text matching. Constant evaluation uses
the StableHLO reference interpreter. Composite operations follow their supplied
decomposition functions, rather than assuming semantics from the composite name.
The private `_schedule.py` structure is temporary code-generation data; it is not
a second public input format. Source operation/location information is retained
for lowering diagnostics. Unsupported operations fail explicitly.

Install `tools/requirements-stablehlo.txt` in a Python 3.12+ environment. The tested
bindings are jaxlib 0.11.2 (including its MLIR registration extension). The compiler
does not import the `jax` package; the frontend and comparison tests do.

```python
import jax.numpy as jnp
from tools.jax_stablehlo import export_function
from tools.program import compile_stablehlo, CompileOptions, KC705

artifact = export_function(lambda x, y: (x + y, x * y),
                           jnp.ones((4, 3)), jnp.ones((4, 3)),
                           output="example.mlirbc")
report = compile_stablehlo(artifact, "example.h",
                          CompileOptions(target=KC705, symbol="example"))
```

The frontend uses `jax.export.export(...).mlir_module_serialized`, rather than
serializing the debugging `compiler_ir()` representation.

```sh
python -m tools.program example.mlirbc -o example.h --target kc705 \
  --symbol example --report example.report.json
```

The same CLI accepts `.mlir` text. `--entry` selects a function, defaulting to
`main`. Reports include argument shapes/dtypes, CPU/TPU placement, workspace and
constant storage, and the numerical policy. Symbols and internal tables are
namespaced so multiple generated programs can share one translation unit.

`--target kc705-rocket` (Python: `KC705_ROCKET`) selects the
[Rocket RV64GC + TPU backend](hardware/kc705_rocket/README.md). The generated C
interface is unchanged; the firmware toolchain uses `rv64imafdc`/`lp64d`, so
floating-point arithmetic executes on Rocket's hardware FPU. Exact int8 matrix
products still use the TPU. Automatic approximate affine placement requires a
target-specific cost model: the Rocket target deliberately does not reuse the
VexRiscv software-float measurements. Explicit forced placement remains available.
Rocket is an experimental RTL target: physical boot is unresolved and work on
it is stopped. VexRiscv remains the active physical backend.

```c
static example_workspace work;
const void *inputs[] = {input_x, input_y};
void *outputs[] = {output_sum, output_product};
int status = example_run(inputs, outputs, &work, &board_qgemm_backend);
```

Each pointer must refer to a correctly typed, contiguous, sufficiently large
buffer matching the reported signature. Bool buffers use one byte per element.
Input/output aliasing is supported: all inputs are copied before any outputs
are written. Workspace must be separate from input/output buffers, and distinct
outputs must not overlap. Caller owns persistent state and repeated execution.

Return values: `0` success, `-1` null argument, `-4` affine encoding out of range
or nonfinite, `-5` missing/failing TPU callback. Failed runs leave output buffers
unchanged; intermediate workspace and device state may have changed. TPU work
never silently runs in a software fallback. The native test callback is explicitly
a reference backend.

## Current lowering coverage

| Category | Supported now |
|---|---|
| Signatures | Multiple inputs/outputs, positive static shapes, scalar tensors; f32/i32/u32/i8/u8/bool |
| Arithmetic | Add, subtract, multiply, float divide, negate, abs, min/max, comparisons, select, sign, conversions; integer/boolean bitwise operations |
| Math | f32 sqrt, exponential, atan2, sine/cosine; composite acos through its StableHLO decomposition |
| Data movement | Reshape, slice, transpose, broadcast, concatenate; constant/runtime gather indices, windows and batching; static iota folding |
| Reduction/update | Single add/multiply/min/max/and/or/xor reductions with scalar initializers; constant/runtime scatter indices, windows and batching, including repeated indices and dropped out-of-range updates; also scatter replacement |
| Matrix work | General static `dot_general` axis layouts lowered to batches of matrix products; default-precision f32×f32→f32 on CPU or i8×i8→i32 on TPU, including dynamic weights and tile tails |
| Control | Acyclic calls and supplied composite decompositions; runtime while loops, nested loops and mixed-type loop-carried state; short compile-time loops may unroll up to 16 steps before outlining the remainder |

Dynamic tensor shapes, conditional `case` regions, arbitrary multi-result
reducers/update functions, convolution in this new frontend, remaining types/math
(for example logarithm), custom calls, and distributed operations require
additional lowerings. Runtime indices do not require dynamic tensor shapes: a
fixed-size tensor can be indexed by values that arrive at runtime. The
existing v1 `.t3m` compiler still supports its existing quantized convolution and
other graph operations; this change does not replace or alter that ABI.

Target descriptors list CPU operations, int8 QGEMM availability, accumulation
limits, libm availability, and an optional workspace limit. These capabilities
describe implementations actually present, rather than claiming that an
arbitrary CPU operation is implemented. Adding an operation requires its
StableHLO legalization, target implementation and execution tests.

## Numerical policy and limits

Default compilation keeps float computation in float32 and does not introduce
quantization or affine reassociation. Compile generated code with
`-ffp-contract=off`, without fast-math, for reproducible comparisons. Floating
reduction/matmul order and libm implementations can still differ from JAX/XLA;
bitwise equivalence to JAX is not promised. Integer add/subtract/multiply wrap
explicitly without undefined signed C overflow. Matrix K is bounded so worst-case
int8 accumulation fits int32. Float/integer conversions saturate and map NaN to
zero for integer outputs; boolean conversions test nonzero.

The bare-metal target has no libm. `--math-mode freestanding
--allow-approximation` enables the supplied float math routines. This is an
explicit numerical policy, not implicit substitution.

Freestanding sine/cosine use a 256-bit fixed-point `2/pi` argument reduction
before evaluating a polynomial on a small interval. This avoids converting huge
angles to int32 or using an inaccurate single-float modulus. A 20,000-pattern
binary32 sample measured maximum absolute error about `5.96e-8` against a double
precision host reference; this is test evidence, not a proof of correct rounding.
Infinity/NaN and signed zero are covered. Double arithmetic in range reduction
uses libgcc on RV32 and has a performance cost.

Runtime loop regions have separate reusable workspaces. Condition and body share
scratch storage through a union. Carry updates follow parallel-assignment
semantics, captures remain explicit, and a failed body call does not publish
partial outputs. Workspace reports include nested regions; tests compare the
reported byte count against C `sizeof`. Loops follow the source stopping
condition, with no implicit execution-time bound.

`--affine-offload --allow-approximation` additionally discovers eligible affine
expressions. It groups repeated coefficient matrices, encodes input values as
two or three balanced base-256 int8 digits, invokes QGEMM, and reconstructs with
int64 arithmetic. Inputs use `--input-fraction-bits` (default 20). Range violations
fail rather than saturate. Coefficients must be integer-representable by default;
`--coefficient-tolerance` explicitly allows coefficient rounding. Reports include
the actual maximum coefficient error. Rounding, float reassociation and subsequent
float output conversion all affect error. No global application error bound is
implied by the coefficient tolerance.

Affine selection uses an explicit, experimental target cost model. The default
`--affine-policy auto` estimates CPU work actually removed (excluding shared
intermediates), packed-register transport, float-to-digit conversion and output
reconstruction. It requires a 15% estimated advantage before selecting a TPU
partition. Targets without a cost model retain CPU arithmetic. The KC705
transport coefficient is calibrated against full CPU/TPU RTL; CPU/conversion
coefficients are conservative starting estimates, not measured per-operation
guarantees. `Target.affine_cost_model` can supply different coefficients.
Exact int8 matrix products still use the declared QGEMM backend; the cost policy
currently governs the optional approximate affine rewrite.

`--affine-policy force` bypasses profitability for measurement and diagnostics,
while retaining legality/range/precision checks. `affine_placement_decisions`
records accepted and rejected candidates, estimated cycles, policy and reasons.
No runtime fallback is introduced. The compiler reports workspace separately
from code, stack, application data and driver storage. Final firmware linking
must enforce the whole board memory budget.

## Generic fusion and packed transport

Fusion uses operation kinds, shapes and SSA use counts. It recognizes no cloth
or other application names. Same-shape, single-consumer elementwise chains use
one loop with typed scalar temporaries, preserving operation order and rounding
boundaries under the compilation flags above. Returned/shared intermediates stay
materialized. Reductions, scatters, TPU calls and control flow are boundaries;
loop bodies are optimized recursively. Static index maps are composed, and
single-consumer reorders can become read-only views with correctly extended
source-buffer lifetimes. `--no-fusion` / `CompileOptions(fusion=False)` disables
these transformations for comparisons or targets that run faster without them.
Fusion is not guaranteed to improve latency on a small CPU cache.

The generic QGEMM driver now requires the existing PACKED_ROW register aperture.
It writes four operands per transaction, caches unchanged operand rows within
one call, and chooses row-parallel or K-parallel use of the cores by tile count.
Cache state never survives a call. Tail padding, signed int32 result validation,
int64 partial accumulation, overflow rejection, bus errors and timeouts remain
checked. No hardware change or cloth-specific kernel is needed. All register
accesses use the existing ordered callback contract.

Observed VexRiscv one-step, instrumented full-SoC RTL measurements at 100 MHz:

| Configuration | Physics step | Inside TPU callbacks |
|---|---:|---:|
| Original scalar-register driver, forced affine, no fusion | 350.81 ms | 232.97 ms |
| Packed driver, forced affine, no fusion | 146.88 ms | 28.90 ms |
| Automatic affine placement, no fusion | 111.22 ms | 0 ms |
| Automatic placement, fusion and index views | 116.44 ms | 0 ms |

Automatic placement retains cloth physics on the board CPU because the affine
partition is slower even with packed transport; camera transforms still use the
TPU in the live application. Fusion reduces this CPU program's workspace from
10,088 to 8,244 bytes but costs about 5% latency in this benchmark. The live build
therefore uses `--no-fusion`, selected from measurements without adding any
application-specific rules to the compiler. Each physics substep advances only
1/7680 simulated second; these results do not establish real-time simulation or
long-run numerical fidelity.

Use `tests/test_stablehlo_soc.py --profile` for generic profiling; optional
`--force-affine`, `--no-affine` and `--no-fusion` provide controlled comparisons.
`profile.json` separates total, TPU-callback and remaining CPU/conversion cycles
and records exact reference output checks.

Rocket changes this tradeoff: eight unfused cloth steps took 4,688,415 RTL cycles,
while generic fusion reduced them to 3,923,626 cycles, with all 180 final float32
words matching the native generated C. These are simulated cycle counts, not
physical FPS. Use `--cpu rocket --steps 8` for the corresponding SoC regression.
The Rocket board build enables fusion; no workload-specific compiler rule is used.

## Verification

```sh
python tests/test_stablehlo_compiler.py -v
python tests/test_stablehlo_rtl.py --out build-stablehlo/rtl
python tests/test_stablehlo_soc.py --out build-stablehlo/soc
```

The first tests execute generated C against JAX, plus hand-written MLIR with JAX
imports forbidden. RTL tests use the actual mailbox driver and accelerator RTL.
The optional SoC test requires the RISC-V toolchain, Verilator and the sibling
`synapse32` UART source (override `--synapse32-dir`). It executes the emitted code
on VexRiscv plus TPU RTL by default, or Rocket plus TPU with `--cpu rocket`, and
checks that no external memory requests occur. `tests/test_rocket_fpu.py` also
checks 640 FP32/FP64 arithmetic and square-root results, including exceptional
values. The production Rocket UART regression is
`sidequests/cloth/compiled_uart_sim.py --board PATH --out PATH`.
Tests never program the physical board or replace an active demo.

The cloth example exports its complete step using this same API:

```sh
python sidequests/cloth/compile_program.py /path/to/jaxsim --affine-offload
python tests/test_stablehlo_soc.py --out build-cloth/stablehlo-soc \
  --artifact build-cloth/stablehlo/cloth.mlirbc \
  --input build-cloth/stablehlo/input.npy
```

Initial cloth smoke result, before the packed-driver/placement work above:
180 outputs match the native generated reference
bit-for-bit in full CPU/TPU RTL, 32,609,362 cycles, no external memory, and 53,468
bytes of code/constants/data/BSS in a 64 KiB linked image with a 4 KiB stack
reservation. This is a simulation result, not physical-board FPS or a speedup.
At 100 MHz those cycles represent about 326 ms for one tiny simulation step.
The host-JAX/physical-TPU transformation preview is a separate workload.

Native generated float-state cloth validation with the forced affine policy
has about 26 micrometres maximum position error at one simulated second, but
about 14.5 centimetres at 1.5 seconds versus JAX. The nonlinear trajectory is
sensitive, so long-run numerical fidelity is not established by the one-step
or RTL checks. Cloth remains a numerical validation workload, not a compiler
special case.

## Failure examples and backend fixes

All six examples below failed before these lowerings were added. They now compile
and execute in the regression suite. These examples are input programs; none is
matched by workload name.

| Example | Previous failure and cause | Implemented lowering |
|---|---|---|
| `lax.fori_loop(0, n, step, state)` | `stablehlo.while`: the guard was required to be compile-time constant | Reusable generated condition/body functions invoked by a board CPU loop |
| `positions[indices]` | `stablehlo.gather`: only precomputed address maps existed | Runtime address generation with axis/window/batch mapping and clamped starts |
| `forces.at[indices].add(updates)` | `stablehlo.scatter`: only constant full-row updates existed | Runtime update addresses with bounds checks and defined reducer handling |
| `A @ B` for `[B,M,K] × [B,K,N]` | `stablehlo.dot_general`: hard-coded rank-2 dimensions | Axis normalization plus per-batch CPU or TPU calls; multiple contracting axes supported |
| `jnp.max(x, axis=0)` | `stablehlo.reduce`: only addition from zero existed | Supported reducer selection and explicit scalar initializer |
| `jnp.sin(x)` | `stablehlo.sine`: no math implementation was registered | Host libm or explicitly enabled freestanding math, including full finite binary32 angle range |

The combined SoC regression executes runtime indexing, sine/cosine, a runtime
loop, batched TPU calls and maximum reduction. It returned four exact reference
outputs in 1,866,707 simulated cycles, with no external memory request; its image
uses 18,004 bytes before stack. Accelerator RTL also verifies TPU calls from a
runtime loop and the complete cloth program. These remain simulation results.

Long-run cloth disagreement is **not only int8 quantization**. Isolating the
policies on the same StableHLO artifact gives:

| Execution policy | Maximum position error at 1 s | At 1.5 s |
|---|---:|---:|
| CPU, host libm, no TPU quantization | 17.3 µm | 8.10 cm |
| CPU, freestanding math, no TPU quantization | 25.9 µm | 12.22 cm |
| CPU + affine int8 TPU offload | 25.7 µm | 14.47 cm |

These measurements compare complete trajectories against JAX, not just one
step from identical state. They show that quantization alone cannot explain the
disagreement and are consistent with accumulated float-evaluation differences
in a sensitive trajectory. They do not establish a complete causal attribution
or fix long-run accuracy. Precision policy, evaluation order and simulation
stability need separate validation; unsupported-operation fixes do not solve
that numerical issue automatically.

Reproduce that isolation with
`python sidequests/cloth/compare_compiler_accuracy.py /path/to/jaxsim`.
The TPU callback in this diagnostic is the native software reference; it isolates
the numerical transformation without conflating it with device transport.

Contracts: [StableHLO specification](https://openxla.org/stablehlo/spec),
[portable artifact API](https://openxla.org/stablehlo/compatibility),
[JAX export](https://docs.jax.dev/en/latest/export/export.html).

## Experimental CORDIC exponential target

The explicit `kc705-cordic` target maps `stablehlo.exponential` to the generic
MMIO hyperbolic CORDIC peripheral at `0x20003000`. Select freestanding math and
allow approximation. Other supported math retains its existing CPU lowering;
exact int8 matrix products still execute on the TPU. Existing KC705 images do
not contain this peripheral: build the no-DDR VexRiscv target with `--cordic`.
A missing peripheral, a busy/rejected command, or a polling timeout returns
`-6` without publishing output buffers. There is no implicit software fallback.

The Q3.29 shift/add core accepts binary32 input/output, reduces by ln(2), and
uses hyperbolic iterations 1–30 with repetitions at 4 and 13. The 40,014-vector
RTL check observed at most 2 float32 ULPs error and 187-cycle maximum latency.
It includes random binary32 patterns, overflow/underflow, infinities, NaNs,
backpressure and reset. This is sampled evidence, not a correct-rounding proof.
Circular sine/cosine, sqrt, and general division remain CPU operations; this
initial peripheral accelerates exponential only.

Physical KC705 verification of the shared showcase firmware measured an
8-token causal attention block at 52.57 ms with software exponential and
45.92 ms with CORDIC (14.5% lower compute time). All 64 output words matched
native generated C exactly for the checked fixtures. The routed image passed
100 MHz timing with a final estimate of 111.36 MHz. These are physical compute
times, excluding UART and pixels; numerical agreement is fixture-specific.
See [the workload showcase](sidequests/showcase/README.md) for measured MLP,
resident banana state, pretrained-model memory limits and reproduction steps.
