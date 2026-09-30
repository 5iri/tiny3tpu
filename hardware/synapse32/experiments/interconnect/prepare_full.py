#!/usr/bin/env python3
"""Prepare baseline synthesis with ONLY the isolated SoC substituted.

Uses baseline-generated DDR/firmware unchanged, writes only to --out under /tmp.
The resulting script is run by the parent or manually with the baseline Yosys.
"""
import argparse
from pathlib import Path

here = Path(__file__).resolve().parent
root = here.parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
out = args.out.resolve()
assert str(out).startswith(('/tmp/', '/private/tmp/')), out
out.mkdir(parents=True, exist_ok=True)
script = (root / 'build-ddr/synth.ys').read_text()
original = str(root / 'hardware/synapse32/synapse32_dram_soc.sv')
assert script.count(original) == 1
script = script.replace(original, str(here / 'synapse32_dram_soc.sv'))
original_output = str(root / 'build-ddr/soc.json')
assert script.count(original_output) == 1
script = script.replace(original_output, str(out / 'soc.json'))
(out / 'synth.ys').write_text(script)
print(out / 'synth.ys')
