"""Exact modular UART FIFO occupancy updates without a control-fed carry chain."""
import hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BASE=ROOT/'build-ddr-dma-uart-reset/uart.v'
def blocks(kind):
    p=kind+'_fifo'
    old=f"""        if ({p}_cleared) begin
            {p}_count <= 5'd0;
        end else if ({p}_pushed && !{p}_popped) begin
            {p}_count <= {p}_count + 1'b1;
        end else if (!{p}_pushed && {p}_popped) begin
            {p}_count <= {p}_count - 1'b1;
        end"""
    new=f"        if ({p}_cleared) begin\n            {p}_count <= 5'd0;\n        end else begin\n"
    new+=f"            {p}_count[0] <= {p}_count[0] ^ ({p}_pushed ^ {p}_popped);\n"
    for i in range(1,5):
        new+=f"            {p}_count[{i}] <= {p}_count[{i}] ^ (({p}_pushed && !{p}_popped && (&{p}_count[{i-1}:0])) || (!{p}_pushed && {p}_popped && !(|{p}_count[{i-1}:0])));\n"
    return old,new+'        end'
def patch_uart(source):
    actual=source
    for kind in ['tx','rx']:
        old,new=blocks(kind);assert actual.count(old)==1;actual=actual.replace(old,new)
    restored=actual
    for kind in ['tx','rx']:
        old,new=blocks(kind);restored=restored.replace(new,old)
    assert restored==source
    return actual
def prove_uart(out):
    proof=out/'uart-prefix-proof';proof.mkdir(exist_ok=False)
    candidate=out/'uart.v';assert candidate.read_text()==patch_uart(BASE.read_text())
    text='module proof(input [4:0] count,input pushed,popped,cleared,rst,output same);\n'
    for name,new in [('gold',False),('actual',True)]:
        block=blocks('rx')[int(new)].replace('rx_fifo_count',name).replace('rx_fifo_pushed','pushed').replace('rx_fifo_popped','popped').replace('rx_fifo_cleared','cleared').replace('<=','=')
        # Evaluate the same old count on all RHS bits (nonblocking semantics).
        import re
        block=re.sub(r'= ([^;]+);',lambda m:'= '+re.sub(r'\b'+name+r'\b','count',m.group(1))+';',block)
        text+=f'reg [4:0] {name};\nalways @* begin\n{name}=count;\nif (rst) {name}=0; else begin\n'+block+'\nend\nend\n'
    text+='assign same=gold==actual;\nendmodule\n';(proof/'proof.v').write_text(text)
    ys=proof/'proof.ys';ys.write_text(f'read_verilog {proof/"proof.v"}\nprep -top proof; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (proof/'proof.log').open('w') as log:subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True)
    paths=[BASE,candidate,Path(__file__).resolve(),yosys,proof/'proof.v',ys,proof/'proof.log',out/'prepared.json']
    (proof/'results.json').write_text(json.dumps(dict(passed=True,added_latency_cycles=0,claim='Exact next occupancy for all 32 counts and all push/pop/clear/reset combinations, including simultaneous events and modular underflow/overflow. Same identical update template for RX and TX; all other UART text, reset ownership, initialization, data FIFOs, interrupts and protocol state remain unchanged.',sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS UART FIFO occupancy for every state and control combination',flush=True)
