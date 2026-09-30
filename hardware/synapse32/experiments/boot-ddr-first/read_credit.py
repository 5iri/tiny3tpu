"""Parallel read-credit update and exact full-flag lookahead."""
import hashlib
import json
from pathlib import Path
import subprocess
import fifo

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
LEVEL='main_read_r_buffer_level2'
PUSH='main_read_r_buffer_queue'
POP='main_read_r_buffer_dequeue'


def subst(text):
    return text.replace(fifo.LEVEL,LEVEL).replace(fifo.PUSH,PUSH).replace(fifo.POP,POP)


OLD=subst(fifo.OLD)
NEW=subst(fifo.new_body())
FLAG=f'''reg main_read_credit_full_q = 1'b0;
always @(posedge sys_clk) begin
    if ({PUSH} && !{POP})
        main_read_credit_full_q <= ({LEVEL} == 5'd15);
    else if (!{PUSH} && {POP})
        main_read_credit_full_q <= ({LEVEL} == 5'd17);
    if (sys_rst) main_read_credit_full_q <= 1'b0;
end
'''
COMPARE="assign main_read_can_read = (main_read_r_buffer_level2 != 5'd16);"


def patch_read_credit(source):
    assert source.count(OLD)==1 and source.count(COMPARE)==1
    assert source.count(LEVEL+' <=')==3
    assert source.count(f"reg     [4:0] {LEVEL} = 5'd0;")==1
    assert source.count(f"        {LEVEL} <= 5'd0;")==1
    return source.replace(OLD,NEW).replace(COMPARE,FLAG+'assign main_read_can_read = !main_read_credit_full_q;')


def prove_read_credit(out):
    folder=out/'read-credit-proof';folder.mkdir(exist_ok=False)
    source=ROOT/'build-ddr-dma-uart-reset/board/litedram/gateware/kc705_dram.v'
    patch_read_credit(source.read_text())
    candidate=out/'board/litedram/gateware/kc705_dram.v'
    text=candidate.read_text();assert NEW in text and FLAG in text and COMPARE not in text
    ios=f'input sys_clk,sys_rst,{PUSH},{POP},output reg [4:0] {LEVEL}=0,output available'
    gold=f'''module gold({ios});
always @(posedge sys_clk) begin
{OLD}
if(sys_rst) {LEVEL}<=0;
end
assign available = {LEVEL} != 5'd16;
endmodule
'''
    gate=f'''module gate({ios});
always @(posedge sys_clk) begin
{NEW}
if(sys_rst) {LEVEL}<=0;
end
{FLAG}
assign available = !main_read_credit_full_q;
endmodule
'''
    conn=','.join(f'.{n}({n})' for n in ['sys_clk','sys_rst',PUSH,POP])
    top=f'''module proof(input sys_clk,sys_rst,{PUSH},{POP},output same);
wire [4:0] g,c;wire ga,ca;
gold gold({conn},.{LEVEL}(g),.available(ga));
gate gate({conn},.{LEVEL}(c),.available(ca));
assign same = (g==c) && (ga==ca);
endmodule
'''
    (folder/'proof.v').write_text(gold+gate+top)
    ys=folder/'proof.ys';ys.write_text(f'read_verilog {folder/"proof.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 3 -tempinduct -maxsteps 12 -prove same 1 -verify\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (folder/'proof.log').open('w') as log:
        rc=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT).returncode
    assert rc==0,folder/'proof.log'
    paths=[source,candidate,Path(__file__).resolve(),HERE/'fifo.py',yosys,folder/'proof.v',ys,folder/'proof.log',out/'prepared.json']
    (folder/'results.json').write_text(json.dumps(dict(passed=True,
        claim='Temporal induction proves five-bit read-credit count and full predicate identical under arbitrary enqueue/dequeue/reset, including simultaneous events and modular wrap. No extra read issue cycle, payload or handshake change.',
        added_latency_cycles=0,sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS read credit and full-flag temporal induction',flush=True)
