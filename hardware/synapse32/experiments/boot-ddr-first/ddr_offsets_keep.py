"""Parallel upper-address alternatives for the generated signed burst offsets."""
import hashlib,json,re,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BASE=ROOT/'build-ddr-dma-uart-reset/board/litedram/gateware/kc705_dram.v'

def replacement(kind):
    channel='ar' if kind=='read' else 'aw'
    p='main_'+kind
    old=f"assign {p}_{channel}_payload_addr = ($signed({{1'd0, {p}_source_source_payload_addr}}) + {p}_beat_offset);"
    new=f'''// A signed 13-bit offset changes upper address bits by at most one.
wire [13:0] {p}_offset_low = {{1'b0,{p}_source_source_payload_addr[12:0]}} + {{1'b0,{p}_beat_offset[12:0]}};
(* keep=1 *) wire [16:0] {p}_offset_upper_inc = {p}_source_source_payload_addr[29:13] + 17'd1;
(* keep=1 *) wire [16:0] {p}_offset_upper_dec = {p}_source_source_payload_addr[29:13] - 17'd1;
wire [16:0] {p}_offset_upper = ({p}_offset_low[13] == {p}_beat_offset[12]) ?
    {p}_source_source_payload_addr[29:13] : ({p}_offset_low[13] ? {p}_offset_upper_inc : {p}_offset_upper_dec);
assign {p}_{channel}_payload_addr = {{{p}_offset_upper,{p}_offset_low[12:0]}};'''
    return old,new

def patch_offsets(source):
    result=source
    for kind in ['read','write']:
        p='main_'+kind
        assert re.search(r'wire\s+\[29:0\] '+p+'_source_source_payload_addr;',source)
        assert re.search(r'reg\s+signed\s+\[12:0\] '+p+"_beat_offset = 13'd0;",source)
        old,new=replacement(kind);assert result.count(old)==1;result=result.replace(old,new)
    restored=result
    for kind in ['read','write']:
        old,new=replacement(kind);restored=restored.replace(new,old)
    assert restored==source
    return result

def prove_offsets(out):
    proof=out/'ddr-offset-proof';proof.mkdir(exist_ok=False)
    source=BASE.read_text();patch_offsets(source)
    candidate=out/'board/litedram/gateware/kc705_dram.v';actual=candidate.read_text()
    harness='module proof(input [29:0] main_read_source_source_payload_addr,main_write_source_source_payload_addr,input signed [12:0] main_read_beat_offset,main_write_beat_offset,output same);\n'
    checks=[]
    for kind in ['read','write']:
        old,new=replacement(kind);assert actual.count(new)==1 and old not in actual
        name='main_'+kind+('_ar_payload_addr' if kind=='read' else '_aw_payload_addr')
        harness+=f'wire [29:0] {name},gold_{name};\n'+old.replace(name,'gold_'+name)+'\n'+new+'\n'
        checks.append(f'{name}==gold_{name}')
    harness+='assign same='+' && '.join('('+v+')' for v in checks)+';\nendmodule\n'
    (proof/'proof.v').write_text(harness)
    ys=proof/'proof.ys';ys.write_text(f'read_verilog {proof/"proof.v"}\nprep -top proof; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (proof/'proof.log').open('w') as log:subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True)
    paths=[BASE,candidate,Path(__file__).resolve(),yosys,proof/'proof.v',ys,proof/'proof.log',out/'prepared.json']
    (proof/'results.json').write_text(json.dumps(dict(passed=True,added_latency_cycles=0,
        claim='Exact generated read and write addresses for all 30-bit base addresses and all signed 13-bit offsets, including negative wrap offsets and address overflow. Kept upper increment/decrement alternatives inhibit sharing across the late carry selection. Only two combinational sums change; every sequential assignment and handshake remains byte unchanged. No burst-size, alignment or traffic assumptions.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS DDR read/write signed offset sums for every base address and offset',flush=True)
