"""Carry-save multiply reduction with eight-bit carry-select result blocks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
CSA_PATH=HERE.parent/'mul-carry-save/prepare.py'
spec=importlib.util.spec_from_file_location('multiply_csa',CSA_PATH)
csa=importlib.util.module_from_spec(spec);spec.loader.exec_module(csa)


def reduction():
    body=csa.NEW.replace('    wire [47:0] combined = sum2 + carry2;', '')
    body+='\n    wire [47:0] combined;\n    wire [6:0] block_carry;\n    assign block_carry[0] = 1\'b0;\n'
    for i in range(6):
        hi,lo=8*i+7,8*i
        body+=f'''    wire [8:0] block_sum_{i} = {{1'b0,sum2[{hi}:{lo}]}} + {{1'b0,carry2[{hi}:{lo}]}};
    wire [7:0] block_inc_{i} = block_sum_{i}[7:0] + 8'd1;
    wire block_propagate_{i} = &block_sum_{i}[7:0];
    assign combined[{hi}:{lo}] = block_carry[{i}] ? block_inc_{i} : block_sum_{i}[7:0];
'''
        terms=[]
        for j in range(i,-1,-1):
            factors=[f'block_propagate_{k}' for k in range(j+1,i+1)]+[f'block_sum_{j}[8]']
            terms.append('('+' & '.join(factors)+')')
        body+=f"    assign block_carry[{i+1}] = "+' | '.join(terms)+';\n'
    return body.rstrip()


def patch_mul(source):
    assert source.count(csa.OLD)==1 and source.count(csa.EXPR)==1
    candidate=source.replace(csa.OLD,reduction()).replace(csa.EXPR,csa.NEWEXPR)
    assert candidate.replace(reduction(),csa.OLD).replace(csa.NEWEXPR,csa.EXPR)==source
    return candidate


def prove_mul(out):
    folder=out/'multiply-proof';folder.mkdir(exist_ok=False)
    source=ROOT/'build-atomic-word-v2/overlay/alu.v'
    candidate=out/'overlay/alu.v'
    assert candidate.read_text()==patch_mul(source.read_text())
    harness='module combine(input [31:0] p00,input signed [33:0] p01,p10,p11,input low_s2,output same);\n'+csa.OLD+'\n'+reduction()+'\nassign same=('+csa.EXPR+') == ('+csa.NEWEXPR+');\nendmodule\n'
    (folder/'combine.v').write_text(harness)
    ys=folder/'proof.ys';ys.write_text(f'read_verilog {folder/"combine.v"}\nprep -top combine\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (folder/'proof.log').open('w') as log:
        rc=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT).returncode
    assert rc==0,folder/'proof.log'
    paths=[source,candidate,Path(__file__).resolve(),CSA_PATH,yosys,folder/'combine.v',ys,folder/'proof.log',out/'prepared.json']
    (folder/'results.json').write_text(json.dumps(dict(passed=True,
        claim='Exact final low/high multiply results for arbitrary signed partial words and selector. Eight-bit carry-select blocks replace the final 48-bit carry-propagating sum after carry-save reduction. All registers, reset behavior and output edges are byte unchanged; zero added instruction or system cycles.',
        added_latency_cycles=0,sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS blocked multiply combine for arbitrary partial words and selector',flush=True)
