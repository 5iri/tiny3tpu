# Compiler reading guide

This compiler translates tensor computations into C for the CPU and accelerator.
Compilation happens on the host. The generated C is built together with the
application firmware and driver into a RISC-V firmware image.

```text
JAX → StableHLO ────────────────┐
                               ↓
                         ExecutionPlan
                               ↑
tinygrad tensors → UOp graph ───┘
       ↑                       ↓
ONNX via OnnxRunner     shared compilation
                               ↓
                  generated C + workspace type
                               ↓
                   application firmware / driver
```

## Start here

1. [compiler.py](compiler.py): compilation options and pass orchestration.
2. [_schedule.py](_schedule.py): `Value`, `Node`, and `ExecutionPlan`; these
   describe arrays, operations, and dependencies.
3. [target.py](target.py): `legalize()` checks supported operations and assigns
   CPU, TPU, or enabled CORDIC execution.
4. [c_backend.py](c_backend.py): emits C and plans intermediate storage.

Placement is decided during compilation. Generated CPU operations execute as C;
selected TPU matrix products call the backend supplied by the firmware.
Runtime loops and inputs still determine which operations execute and how often.

## Then follow one frontend

| File | Responsibility |
| --- | --- |
| [stablehlo.py](stablehlo.py) | Read StableHLO and lower it into the execution plan |
| [tinygrad_frontend.py](tinygrad_frontend.py) | Lower tinygrad UOps, including ONNX graphs loaded through OnnxRunner |

Both feed the same shared compiler. The tinygrad route does not require an
intermediate StableHLO artifact.

## Optimizations and hardware code generation

| File | Responsibility |
| --- | --- |
| [cost.py](cost.py) | Cost estimates used for placement |
| [optimize.py](optimize.py) | Index composition and elementwise fusion grouping |
| [partition.py](partition.py) | Optional approximate affine offload |
| [mmio_codegen.py](mmio_codegen.py) | Specialized fixed-shape TPU register kernels |

## Public entry points

- [__init__.py](__init__.py): Python API, including `compile_stablehlo`,
  `compile_tinygrad`, and `compile_onnx_via_tinygrad`.
- [__main__.py](__main__.py): StableHLO CLI, invoked with `python -m tools.program`.

## Tests to read alongside the implementation

- [test_stablehlo_compiler.py](../../tests/test_stablehlo_compiler.py): native generated-C execution and compiler behavior.
- [test_tinygrad_openpilot.py](../../tests/test_tinygrad_openpilot.py): tinygrad and ONNX frontend cases.
- [test_stablehlo_rtl.py](../../tests/test_stablehlo_rtl.py): accelerator RTL integration.
- [test_stablehlo_soc.py](../../tests/test_stablehlo_soc.py): generated firmware running in CPU/TPU simulation.

The full StableHLO contract and numerical policies are documented in
[docs_stablehlo.md](../../docs_stablehlo.md).
