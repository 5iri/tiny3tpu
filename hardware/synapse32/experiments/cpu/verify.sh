#!/usr/bin/env bash
set -euo pipefail
experiment=$(cd "$(dirname "$0")" && pwd)
cpu=${1:-/Users/siriboi/github/synapse32}
yosys=${YOSYS:-/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys}
work=$(mktemp -d /tmp/tiny3tpu-cpu-comb.XXXXXX)
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
printf 'Evidence directory: %s\n' "$work"
for module in decoder csr_exec; do
    candidate="$experiment/$module.v"
    if [[ $module == decoder ]]; then candidate="$experiment/rejected/decoder.v"; fi
    "$yosys" -Q -T -p "
        read_verilog -sv -I$cpu/rtl/include $cpu/rtl/core_modules/$module.v;
        rename $module gold;
        read_verilog -sv -I$cpu/rtl/include $candidate;
        rename $module gate;
        proc; memory; opt;
        equiv_make gold gate equiv;
        hierarchy -top equiv;
        equiv_simple;
        equiv_status -assert;
    " > "$work/$module.equiv.log" 2>&1
    for variant in gold gate; do
        source="$cpu/rtl/core_modules/$module.v"
        if [[ $variant == gate ]]; then source="$candidate"; fi
        "$yosys" -Q -T -m slang -p "
            read_slang --single-unit --top $module -I$cpu/rtl/include $source;
            synth_xilinx -family xc7 -top $module -noiopad -noclkbuf;
            check -assert;
            stat;
            ltp -noff;
            write_json $work/$module.$variant.json;
        " > "$work/$module.$variant.log" 2>&1
    done
done
printf 'All combinational equivalence and mapping checks passed.\n'
