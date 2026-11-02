# Tools

Start with [the compiler](program/README.md). Its implementation is contained in
`program/`. Top-level scripts support model export, board builds, and hardware
validation.

## Compiler and model export

| Path | Purpose |
| --- | --- |
| [program/](program/README.md) | StableHLO and tinygrad/ONNX frontends, shared compiler, C generation |
| [jax_stablehlo.py](jax_stablehlo.py) | Export JAX functions to StableHLO |
| [jax_export.py](jax_export.py) | Older quantized graph export path |
| [jax_affine_lowering.py](jax_affine_lowering.py) | JAX affine lowering utilities |
| [requirements-stablehlo.txt](requirements-stablehlo.txt) | StableHLO/JAX dependencies |

The older JSON → `.t3m` compiler is in `../src/compiler.cpp`; its runtime is
`../src/runtime.c`. Read that separately from the generated-C compiler.

## Board tooling

| Entry point | Purpose |
| --- | --- |
| [kc705_open_build.py](kc705_open_build.py) | Main board build flow |
| [kc705_export_bitstream.py](kc705_export_bitstream.py) | Bitstream export and checks |
| [kc705_vexriscv_sim.py](kc705_vexriscv_sim.py) | VexRiscv system simulation |

Other `kc705_*.py` scripts cover capture, programming, alternate board builds,
and DDR bring-up. Read them when following the relevant hardware guide under
`../hardware/`.

## Synapse32 validation

The retained `synapse32_*.py` scripts provide timing analysis, timing models,
structural audits, and system/workload reports used by builds and tests. These
files are not compiler passes. Their current paths preserve existing callers.

Use a targeted search instead of reading the directory alphabetically:

```sh
rg --files tools -g 'synapse32_*timing*'
rg --files tools -g 'synapse32_*report*'
rg -n 'script_name' tools tests hardware CMakeLists.txt
```
