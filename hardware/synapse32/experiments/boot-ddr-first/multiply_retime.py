"""Move carry-save reduction across the existing partial-product register edge."""
import hashlib,json,re,subprocess
from pathlib import Path
import multiply_single_csa as single
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BASE=ROOT/'build-atomic-word-v2/overlay/alu.v'
def patch_mul(source):
    s=single.patch_mul(source)
    start=s.index('module synapse32_system_multiply (');head=s[:start];body=s[start:]
    products={}
    for p in ['p00','p01','p10','p11']:
        line=re.search(r'^            '+p+r'<=([^;]+);$',body,re.M)
        assert line;products[p]=line.group(1);body=body.replace(line.group(0)+'\n','')
    old='    reg [31:0] p00;\n    reg signed [33:0] p01, p10, p11;'
    new='    wire [31:0] p00 = '+products['p00']+';\n'
    new+='\n'.join('    wire signed [33:0] '+p+' = '+products[p]+';' for p in ['p01','p10','p11'])
    assert body.count(old)==1;body=body.replace(old,new)
    body=body.replace('wire [47:0] sum2 =','wire [47:0] sum_next =').replace('wire [47:0] carry2 =','wire [47:0] carry_next =')
    body=body.replace('    wire [47:0] combined;', '    reg [47:0] sum2, carry2;\n    reg [15:0] low16;\n    wire [47:0] combined;')
    body=body.replace('p00<=0; p01<=0; p10<=0; p11<=0; result<=0;', 'sum2<=0; carry2<=0; low16<=0; result<=0;')
    body=body.replace('            low_s2<=instr_id==INSTR_MUL;', '            sum2<=sum_next; carry2<=carry_next; low16<=p00[15:0];\n            low_s2<=instr_id==INSTR_MUL;')
    body=body.replace('result<=low_s2 ? {combined[15:0],p00[15:0]}', 'result<=low_s2 ? {combined[15:0],low16}')
    assert 'p00<=' not in body and 'p01<=' not in body
    return head+body

def abstract_body(text,name):
    body=text[text.index('module synapse32_system_multiply ('):]
    body=body[body.index('    reg low_s2;'):]
    # The exact same four product expressions are abstracted to arbitrary
    # shared inputs; no numerical/sign assumptions about products are needed.
    gold=single.patch_mul(BASE.read_text())
    for p,v in [('p00','v00'),('p01','v01'),('p10','v10'),('p11','v11')]:
        expr=re.search(r'^            '+p+r'<=([^;]+);$',gold,re.M).group(1)
        assert body.count(expr)==1,(name,p)
        body=body.replace(expr,v)
    assert body.count('instr_id==INSTR_MUL')==1
    body=body.replace('instr_id==INSTR_MUL','low_input')
    assert 'instr_id' not in body
    header=f'module {name}(input clk,rst,low_input,input [31:0] v00,input signed [33:0] v01,v10,v11,output reg [31:0] result);\n'
    return header+body

def prove_mul(out):
    proof=out/'multiply-proof';proof.mkdir(exist_ok=False)
    candidate=out/'overlay/alu.v';assert candidate.read_text()==patch_mul(BASE.read_text())
    gold=single.patch_mul(BASE.read_text())
    source=abstract_body(gold,'gold')+'\n'+abstract_body(candidate.read_text(),'actual')
    source+='\nmodule proof(input clk,rst,low_input,input [31:0] v00,input signed [33:0] v01,v10,v11,output same);\nwire [31:0] a,b;\ngold g(clk,rst,low_input,v00,v01,v10,v11,a);\nactual n(clk,rst,low_input,v00,v01,v10,v11,b);\nassign same=a==b;\nendmodule\n'
    (proof/'retime.v').write_text(source)
    ys=proof/'proof.ys';ys.write_text(f'read_verilog {proof/"retime.v"}\nprep -top proof; flatten; opt; check -assert; sat -seq 3 -set-init-zero -tempinduct -maxsteps 8 -prove same 1 -verify;\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (proof/'proof.log').open('w') as log:subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    paths=[BASE,candidate,Path(__file__).resolve(),HERE/'multiply_single_csa.py',single.CSA_PATH,yosys,proof/'retime.v',ys,proof/'proof.log',out/'prepared.json']
    (proof/'results.json').write_text(json.dumps(dict(passed=True,added_latency_cycles=0,
        claim='Temporal induction of exact result value on every existing output edge, from the common all-zero reset state and with arbitrary reset on every subsequent edge. Identical product expressions are abstracted to arbitrary shared 32/34-bit inputs each edge, and the low/high selector is arbitrary. Existing single-CSA arithmetic identity is separately proved by the retained parent. Total operand-to-result latency and CPU/system cadence requirements are unchanged; only the partial-product/CSA register boundary moves.',
        parent_arithmetic_proof=str(ROOT/'build-ddr-uart-prefix/multiply-proof/results.json'),sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS multiply register-boundary temporal induction',flush=True)
