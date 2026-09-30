#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${SYNAPSE32_SOURCE:-/Users/siriboi/github/synapse32}"
BOARD="$(cd "$HERE/../.." && pwd)"
BUILD="$(mktemp -d "$HERE/build.XXXXXX")"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
iverilog -g2012 -s divider_tb -o "$BUILD/divider_tb" "$HERE/divider.v" "$HERE/divider_tb.sv"
vvp "$BUILD/divider_tb" | tee "$BUILD/divider.log"
files=("$HERE/riscv_cpu.v" "$HERE/execution_unit.v" "$HERE/alu.v" "$HERE/divider.v"
       "$SOURCE/rtl/memory_unit.v" "$SOURCE/rtl/writeback.v")
for f in "$SOURCE"/rtl/core_modules/*.v "$SOURCE"/rtl/pipeline_stages/*.v; do
    case "$f" in
        */alu.v|*/divider.v) ;;
        */csr_exec.v) files+=("${CSR_OVERLAY:-$f}");;
        *) files+=("$f");;
    esac
done
for gated in 0 1; do
    verilator --binary --timing -j 2 -Wno-fatal --top-module cpu_tb \
        -GGATED="$gated" --Mdir "$BUILD/obj$gated" \
        -DSYNAPSE32_CLOCK_SIM -I"$SOURCE/rtl/include" \
        "${files[@]}" "$BOARD/synapse32_memory_sequencer.sv" \
        "$BOARD/synapse32_clock_enable.sv" "$HERE/cpu_tb.sv" \
        >"$BUILD/compile$gated.log" 2>&1
    "$BUILD/obj$gated/Vcpu_tb" | tee "$BUILD/run$gated.log"
    verilator --binary --timing -j 2 -Wno-fatal --top-module cpu_collision_tb \
        -GGATED="$gated" --Mdir "$BUILD/collision$gated" \
        -DSYNAPSE32_CLOCK_SIM -I"$SOURCE/rtl/include" \
        "${files[@]}" "$BOARD/synapse32_memory_sequencer.sv" \
        "$BOARD/synapse32_clock_enable.sv" "$HERE/cpu_collision_tb.sv" \
        >"$BUILD/compile-collision$gated.log" 2>&1
    "$BUILD/collision$gated/Vcpu_collision_tb" | tee "$BUILD/collision$gated.log"
done
printf 'Evidence: %s\n' "$BUILD"
