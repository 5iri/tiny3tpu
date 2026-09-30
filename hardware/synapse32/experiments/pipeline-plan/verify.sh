#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SOURCE="${SYNAPSE32_SOURCE:-/Users/siriboi/github/synapse32}"
mkdir -p "$TASK_DIR/build"
iverilog -g2012 -s forward_lookahead_tb -I "$SOURCE/rtl/include" \
  -o "$TASK_DIR/build/forward_lookahead.vvp" \
  "$SOURCE/rtl/pipeline_stages/ID_EX.v" \
  "$SOURCE/rtl/pipeline_stages/EX_MEM.v" \
  "$SOURCE/rtl/pipeline_stages/MEM_WB.v" \
  "$SOURCE/rtl/pipeline_stages/forwarding_unit.v" \
  "$TASK_DIR/forward_lookahead.sv" "$TASK_DIR/forward_lookahead_tb.sv"
vvp "$TASK_DIR/build/forward_lookahead.vvp" | tee "$TASK_DIR/build/test.log"
