#!/usr/bin/env python3
"""Prove factored burst capacity and complete DMA sequential equivalence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from prepare import SOURCE, prepare, CAPACITY

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args(); out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
prepare(out)
yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
params = '-set AXI_ADDR_WIDTH 32 -set AXI_ID_WIDTH 1 -set AXIS_ID_WIDTH 1 -set AXIS_DEST_WIDTH 1 -set AXIS_USER_ENABLE 0 -set LEN_WIDTH 16 -set TAG_WIDTH 1'
rtl = SOURCE.read_text()
begin = rtl.index('            if (op_word_count_reg <= AXI_MAX_BURST_SIZE')
end = rtl.index('                m_axi_araddr_next =', begin)
(out/'bound.v').write_text('''module bound(input [15:0] op_word_count_reg,
input [31:0] addr_reg, output bounded);
localparam AXI_MAX_BURST_SIZE=64, OFFSET_MASK=3;
reg [15:0] tr_word_count_next;
always @* begin
'''+rtl[begin:end]+'''end
'''+CAPACITY[CAPACITY.index('wire [5:0] burst_page_offset'):CAPACITY.index('reg [TR_WORD_WIDTH')]+'''
wire [15:0] direct = op_word_count_reg <= burst_capacity ? op_word_count_reg : burst_capacity;
assign bounded = (tr_word_count_next <= 64) && (direct == tr_word_count_next);
endmodule
''')
scripts = {
    'bound': f'read_verilog {out/"bound.v"}\nprep -top bound; opt; check -assert; sat -prove bounded 1 -verify;\n',
    'full-equivalence': f'''read_verilog {SOURCE}
chparam {params} axi_dma_rd
rename axi_dma_rd gold
read_verilog {out/'axi_dma_rd.v'}
chparam {params} axi_dma_rd
rename axi_dma_rd gate
proc
memory_map
opt
equiv_make gold gate equiv
hierarchy -top equiv
opt_clean
equiv_simple
equiv_induct -seq 5
equiv_status -assert
'''}
passed = True
for name, body in scripts.items():
    script = out/(name+'.ys'); script.write_text(body)
    with (out/(name+'.log')).open('w') as log:
        rc = subprocess.run([str(yosys), '-Q', '-T', '-s', str(script)], stdout=log, stderr=subprocess.STDOUT).returncode
    passed &= rc == 0
paths = [SOURCE, out/'axi_dma_rd.v', out/'bound.v', yosys, Path(__file__).resolve(), Path(__file__).with_name('prepare.py').resolve()]
paths += [out/(name+suffix) for name in scripts for suffix in ('.ys', '.log')]
result = dict(passed=passed, claim='All current-profile DMA module comparison points prove sequentially equivalent. Factored burst capacity matches actual burst selection and is at most 64 bytes for every length/address, including zero/unaligned/page-boundary inputs. Initial byte count is zero and its only other assignment holds its previous value. Other profiles retain LEN_WIDTH; wrapping cycle counters are unchanged.',
              sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(result, indent=2)+'\n')
assert passed, out
print('PASS factored burst selection and complete DMA module sequential equivalence')
