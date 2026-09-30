#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${SYNAPSE32_SOURCE:-/Users/siriboi/github/synapse32}"
YOSYS="${YOSYS:-/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys}"
BUILD="$(mktemp -d "$HERE/synth.XXXXXX")"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
files=("$HERE/riscv_cpu.v" "$HERE/execution_unit.v" "$HERE/alu.v" "$HERE/divider.v"
       "$SOURCE/rtl/memory_unit.v" "$SOURCE/rtl/writeback.v")
for f in "$SOURCE"/rtl/core_modules/*.v "$SOURCE"/rtl/pipeline_stages/*.v; do
    case "$f" in
        */alu.v|*/divider.v) ;;
        */csr_exec.v) files+=("${CSR_OVERLAY:-$f}");;
        *) files+=("$f");;
    esac
done
"$YOSYS" -Q -T -m slang -p "
    read_slang --allow-use-before-declare --single-unit --top riscv_cpu -I$SOURCE/rtl/include ${files[*]};
    hierarchy -check -top riscv_cpu;
    proc; opt; check -assert;
    scc -expect 0;
    select -assert-none t:\$div t:\$mod t:\$divfloor t:\$modfloor;
    stat;
    write_json $BUILD/cpu.coarse.json;
    synth_xilinx -family xc7 -top riscv_cpu -noiopad -noclkbuf;
    check -assert;
    stat;
    write_json $BUILD/cpu.xc7.json;
" >"$BUILD/cpu.log" 2>&1
printf 'Synthesis passed, no divide/modulo cells. Evidence: %s\n' "$BUILD"
