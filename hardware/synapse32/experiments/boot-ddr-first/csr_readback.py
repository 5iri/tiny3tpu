"""Use address predicates captured on the existing edge for all CSR read banks."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from csr_predecode import BASE, CAPTURE, DECL, NEXT, ENABLE, capture, patch_csr

HERE=Path(__file__).resolve().parent
EXTRA="reg [50:0] read_csr_address_q = 51'd1;"

def blocks(source):
    result=[]
    for bank,count in [(0,2),(1,19),(2,49)]:
        name=f'builder_interface{bank}_bank_bus_dat_r'
        pat=rf"    {name} <= 1'd0;\n    if \(builder_csrbank{bank}_sel\) begin\n        case \(builder_interface{bank}_bank_bus_adr\[8:0\]\)\n(.*?)        endcase\n    end"
        found=list(re.finditer(pat,source,re.S));assert len(found)==1
        old=found[0][0]
        arms=re.findall(r"\d+'d(\d+): begin\n                "+name+r" <= (\w+);\n            end",found[0][1])
        assert len(arms)==count and [int(i) for i,v in arms]==list(range(count))
        assert source.count(name+' <=')==count+1,'Additional writer/reset needs a new proof'
        assert re.search(r'reg\s+\[31:0\] '+name+r" = 32'd0;",source)
        assert f'assign builder_interface{bank}_bank_bus_adr = builder_adr;' in source
        assert re.search(r'assign builder_csrbank'+str(bank)+r"_sel = \(builder_interface"+str(bank)+r"_bank_bus_adr\[13:9\] == \d+'d"+str(bank)+r'\);',source)
        terms=[]
        for i,value in arms:
            bit=int(i)+(2 if bank==2 else 0)
            pred=f'phy_csr_address_q[{i}]' if bank==1 else f'read_csr_address_q[{bit}]'
            terms.append(f'({{32{{{pred}}}}} & {value})')
        new=f'    {name} <= '+' |\n        '.join(terms)+';'
        result.append((bank,name,old,new,arms))
    return result

def extra_capture():
    values=[0,1]+list(range(1024,1073))
    return 'always @(posedge sys_clk) begin\n    if ('+ENABLE+') begin\n'+''.join(
        f"        read_csr_address_q[{i}] <= ({NEXT} == 14'd{v});\n" for i,v in enumerate(values))+'    end\nend\n'

def patch_readback(source):
    assert source.count(DECL)==1 and source.count(capture())==1
    result=source.replace(DECL,DECL+'\n'+EXTRA+'\n'+extra_capture())
    for bank,name,old,new,arms in blocks(source):
        result=result.replace(old,new)
    restored=result.replace(DECL+'\n'+EXTRA+'\n'+extra_capture(),DECL)
    for bank,name,old,new,arms in blocks(source): restored=restored.replace(new,old)
    assert restored==source
    return result

def prove_readback(out):
    folder=out/'csr-readback-proof';folder.mkdir(exist_ok=False)
    source=patch_csr(BASE.read_text()); entries=blocks(source)
    candidate=out/'board/litedram/gateware/kc705_dram.v'
    actual=candidate.read_text()
    assert actual.count(EXTRA)==1 and actual.count(extra_capture())==1
    for bank,name,old,new,arms in entries:
        assert actual.count(new)==1 and old not in actual
        assert actual.count(name+' <=')==1
    data_names=sorted({v for _,_,_,_,arms in entries for i,v in arms})
    harness='module proof(input sys_clk,input '+ENABLE+',input [13:0] '+NEXT+',\n'+','.join('input [31:0] '+n for n in data_names)+',output same);\n'
    harness+="reg [13:0] builder_interface1_adr=0;\n"+DECL+'\n'+EXTRA+'\n'+extra_capture()
    harness+='always @(posedge sys_clk) begin\n'+capture()+'\nend\n'
    checks=[]
    for bank,name,old,new,arms in entries:
        harness+=f"wire [13:0] builder_interface{bank}_bank_bus_adr=builder_interface1_adr;\nwire builder_csrbank{bank}_sel=builder_interface1_adr[13:9]==5'd{bank};\n"
        harness+=f'reg [31:0] gold_{name}=0, gate_{name}=0;\nalways @(posedge sys_clk) begin\n'
        harness+=old.replace(name,'gold_'+name)+'\n'+new.replace(name,'gate_'+name)+'\nend\n'
        checks.append(f'gold_{name}==gate_{name}')
    # Include decode invariants in the induction hypothesis.
    for i,v in enumerate([0,1]+list(range(1024,1073))): checks.append(f"read_csr_address_q[{i}]==(builder_interface1_adr==14'd{v})")
    for i in range(19): checks.append(f"phy_csr_address_q[{i}]==(builder_interface1_adr==14'd{512+i})")
    harness+='assign same='+' && '.join('('+v+')' for v in checks)+';\nendmodule\n'
    (folder/'proof.v').write_text(harness)
    ys=folder/'proof.ys';ys.write_text(f'read_verilog {folder/"proof.v"}\nprep -top proof; flatten; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -prove same 1 -verify;\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (folder/'proof.log').open('w') as log:
        subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True)
    paths=[Path(__file__).resolve(),BASE,candidate,HERE/'csr_predecode.py',folder/'proof.v',ys,folder/'proof.log',yosys,out/'prepared.json']
    (folder/'results.json').write_text(json.dumps(dict(passed=True,added_predicates=51,read_banks=3,read_addresses=70,added_latency_cycles=0,
        claim='Temporal induction of every 32-bit read-bank result for arbitrary 32-bit values, full addresses and capture enables, including hold and INIT. Predicates use existing address edge; all original registered read edges preserved. Actual source blocks extracted, only read muxes replaced, no access strobes or writes changed.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS all three CSR read banks and 70 addresses; no added access edge',flush=True)
