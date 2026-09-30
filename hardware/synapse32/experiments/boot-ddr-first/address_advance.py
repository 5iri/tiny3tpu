"""Carry-select DMA address and remaining-byte updates, without another cycle."""
from pathlib import Path
import hashlib
import json
import subprocess
import terminal

HERE = Path(__file__).resolve().parent
DECL = "reg [TR_WORD_WIDTH-1:0] tr_word_count_reg = {TR_WORD_WIDTH{1'b0}}, tr_word_count_next;"
ADVANCE = '''
// A short-profile transfer is at most 64 bytes. Compute upper carry/borrow
// alternatives before the selected transfer length reaches the low six bits.
wire [AXI_ADDR_WIDTH-1:0] address_advance;
wire [LEN_WIDTH-1:0] remaining_advance;
generate if (SHORT_BURST_PROFILE) begin : short_advance
    // This is the exact STATE_START byte selection. Referencing the procedural
    // temporary outside its block would unnecessarily retain its hold register.
    wire [6:0] byte_count = op_word_count_reg <= burst_capacity ? op_word_count_reg : burst_capacity;
    wire [6:0] address_low = {1'b0, addr_reg[5:0]} + byte_count;
    wire [25:0] address_high_plus_one = addr_reg[31:6] + 26'd1;
    assign address_advance = {address_low[6] ? address_high_plus_one : addr_reg[31:6], address_low[5:0]};
    wire [6:0] remaining_low = {1'b0, op_word_count_reg[5:0]} - byte_count;
    wire [9:0] remaining_high_minus_one = op_word_count_reg[15:6] - 10'd1;
    assign remaining_advance = {remaining_low[6] ? remaining_high_minus_one : op_word_count_reg[15:6], remaining_low[5:0]};
end else begin : general_advance
    assign address_advance = addr_reg + tr_word_count_next;
    assign remaining_advance = op_word_count_reg - tr_word_count_next;
end endgenerate
'''


def patch_dma(source):
    source = terminal.patch_dma(source)
    assert source.count(DECL) == 1
    old = '                    addr_next = addr_reg + tr_word_count_next;\n                    op_word_count_next = op_word_count_reg - tr_word_count_next;'
    assert source.count(old) == 1
    return source.replace(DECL, DECL+ADVANCE).replace(old,
        '                    addr_next = address_advance;\n                    op_word_count_next = remaining_advance;')


def prove_dma(out):
    root = HERE.parents[3]; proof = out/'dma-proof'; proof.mkdir(exist_ok=False)
    source = root/'build-ddr-dma-uart-reset/axi_dma_wr.v'; candidate = out/'axi_dma_wr.v'
    assert candidate.read_text() == patch_dma(source.read_text())
    yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    params = '-set AXI_ADDR_WIDTH 32 -set AXI_ID_WIDTH 1 -set AXIS_ID_WIDTH 1 -set AXIS_DEST_WIDTH 1 -set AXIS_USER_ENABLE 0 -set LEN_WIDTH 16 -set TAG_WIDTH 1'
    script = proof/'prepare-state-proof.ys'; script.write_text(f'''read_verilog {source}
chparam {params} axi_dma_wr
rename axi_dma_wr gold
read_verilog {candidate}
chparam {params} axi_dma_wr
rename axi_dma_wr gate
proc
memory_map
opt
write_rtlil {proof/'prepared.il'}
write_json {proof/'prepared-netlist.json'}
''')

    def run(name):
        with (proof/(name+'.log')).open('w') as log:
            rc = subprocess.run([str(yosys),'-Q','-T','-s',str(proof/(name+'.ys'))],stdout=log,stderr=subprocess.STDOUT).returncode
        if rc: raise SystemExit('FAIL DMA '+name+': '+str(proof))

    run('prepare-state-proof')
    modules = json.loads((proof/'prepared-netlist.json').read_text())['modules']
    gold, gate = modules['gold'], modules['gate']
    def state_bits(module):
        assert not any('latch' in c['type'].lower() or c['type'].startswith('$mem') for c in module['cells'].values())
        return {b for c in module['cells'].values() if 'dff' in c['type'].lower() for b in c['connections']['Q']}
    gq, cq = state_bits(gold), state_bits(gate)
    protected = set(gold['ports']) | {n for n,v in gold['netnames'].items()
        if all(b in gq or isinstance(b,str) for b in v['bits'])}
    shared = set(gold['netnames']) & set(gate['netnames'])
    # Preserve every sequential state bit and every module port as a comparison
    # boundary. Keep combinational cones intact: an independently abstracted
    # seven-bit burst_capacity would discard its actual <=64 relationship.
    for module, qbits in [(gold,gq),(gate,cq)]:
        covered = {b for n in protected & shared for b in module['netnames'][n]['bits']}
        assert qbits <= covered
    assert gold['ports'].keys() == gate['ports'].keys() and len(gq) == len(cq)
    blocked = sorted(n for n in shared-protected if not n.startswith('$'))
    (proof/'combinational-cuts.txt').write_text('\n'.join(blocked)+'\n')
    (proof/'state-boundaries.json').write_text(json.dumps(dict(protected=sorted(protected),
        intact_combinational_cones=blocked,state_bits=len(gq),all_state_bits_compared=True),indent=2)+'\n')
    (proof/'state-proof.ys').write_text(f'''read_rtlil {proof/'prepared.il'}
equiv_make -blacklist {proof/'combinational-cuts.txt'} gold gate equiv
hierarchy -top equiv
opt_clean
equiv_simple
equiv_induct -seq 5
equiv_status -assert
''')
    run('state-proof')
    rtl = source.read_text()
    capacity = rtl[rtl.index('wire [5:0] burst_page_offset'):rtl.index('reg [TR_WORD_WIDTH-1:0]')]
    (proof/'exact.v').write_text('''module exact_advance(input [31:0] addr_reg,input [15:0] op_word_count_reg,output same);
localparam SHORT_BURST_PROFILE=1, AXI_ADDR_WIDTH=32, LEN_WIDTH=16;
'''+capacity+'''wire [6:0] tr_word_count_next = op_word_count_reg <= burst_capacity ? op_word_count_reg : burst_capacity;
'''+ADVANCE+'''wire [31:0] old_address=addr_reg+tr_word_count_next;
wire [15:0] old_remaining=op_word_count_reg-tr_word_count_next;
assign same=(tr_word_count_next<=64)&&(address_advance==old_address)&&(remaining_advance==old_remaining);
endmodule
''')
    (proof/'exact.ys').write_text(f'read_verilog {proof/"exact.v"}\nprep -top exact_advance; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
    run('exact')
    paths = [source,candidate,yosys,Path(__file__).resolve(),HERE/'terminal.py',
             HERE.parent/'dma-write-last/prepare.py',HERE.parent/'dma-write-short/prepare.py']+list(proof.iterdir())
    (proof/'results.json').write_text(json.dumps(dict(passed=True,all_state_bits_compared=True,state_bits=len(gq),
        claim='Complete current-profile DMA sequential state/port equivalence with combinational cones preserved, including last-cycle flags and carry-select address/remaining-byte updates. Separate exact arithmetic proof includes the actual burst-capacity bounds for all addresses/lengths. No traffic, initialization, zero-length or page-crossing assumptions.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS complete DMA carry-select equivalence',flush=True)
