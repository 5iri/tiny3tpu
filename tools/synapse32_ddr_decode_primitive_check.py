#!/usr/bin/env python3
"""Check the composed decode against actual Yosys Xilinx LUT simulation models."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from synapse32_ddr_decode_equivalence import CONE, TARGET

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
old_path = root / 'build-ddr-pre-fixup-parallel8/pre-fixup.json'
new_path = a.candidate.resolve()
gold = json.loads(old_path.read_text())['modules']['top']['cells']
gate = json.loads(new_path.read_text())['modules']['top']['cells']
library = Path('/Users/siriboi/.apio/packages/oss-cad-suite/share/yosys/xilinx/cells_sim.v')
out = a.out.resolve()
out.mkdir(parents=True, exist_ok=False)


def ports(cell):
    return {cell['attributes']['X_ORIG_PORT_' + p]: bs[0] for p, bs in cell['connections'].items()}


inputs = [ports(gate[TARGET])[f'I{i}'] for i in range(5)]
names = {b: f'stimulus[{i}]' for i, b in enumerate(inputs)}
for i, name in enumerate(CONE):
    names[ports(gold[name])['O']] = f'gold{i}'
lines = ['module tb;', 'reg [4:0] stimulus;', 'wire gold0, gold1, gold2, candidate;', 'integer i;']
for index, name in enumerate(CONE):
    cell = gold[name]
    size = int(cell['attributes']['X_ORIG_TYPE'][3:])
    mapping = ports(cell)
    pins = [f'.I{i}({names[mapping[f"I{i}"]]})' for i in range(size)]
    pins.append(f'.O(gold{index})')
    lines.append(f'LUT{size} #(.INIT({1 << size}\'b{cell["parameters"]["INIT"]})) g{index} ({", ".join(pins)});')
cell = gate[TARGET]
pins = [f'.I{i}(stimulus[{i}])' for i in range(5)] + ['.O(candidate)']
lines.append(f'LUT5 #(.INIT(32\'b{cell["parameters"]["INIT"]})) dut ({", ".join(pins)});')
lines += ['initial begin', 'for (i=0; i<32; i=i+1) begin', 'stimulus=i; #1;',
          'if (gold2 !== candidate) $fatal(1, "Mismatch at %d", i);', 'end',
          '$display("PASS all 32 input assignments using mapped LUT primitives");', '$finish;', 'end', 'endmodule']
testbench = out / 'tb.v'
testbench.write_text('\n'.join(lines) + '\n')
iverilog, vvp = Path(shutil.which('iverilog')), Path(shutil.which('vvp'))
commands = [[str(iverilog), '-g2012', '-s', 'tb', '-o', str(out / 'sim'), str(library), str(testbench)],
            [str(vvp), str(out / 'sim')]]
results = []
for command in commands:
    r = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    results.append(dict(command=command, exit_code=r.returncode, output=r.stdout))
    assert r.returncode == 0, r.stdout
assert 'PASS all 32' in results[-1]['output']
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
record = dict(passed=True, exhaustive_assignments=32, commands=results, added_registers=0,
              sha256={str(p): digest(p) for p in [old_path, new_path, library, testbench, iverilog, vvp, Path(__file__).resolve()]})
(out / 'results.json').write_text(json.dumps(record, indent=2) + '\n')
print(results[-1]['output'].strip())
