"""Exact local DMA/TPU acceptance without the external-memory-ready cone."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
WIRES='''    wire dma_local_accept = !rst && idle && req_valid && dma_address;
    wire tpu_local_accept = !rst && idle && req_valid && tpu_address;
'''
ANCHOR='    wire uart_accept = idle && req_valid && uart_address;\n'


def patch_local(source):
    assert source.count(ANCHOR)==1
    for name in ('dma','tpu'):
        assert source.count('accept && '+name+'_address')==2
    result=source.replace(ANCHOR,ANCHOR+WIRES)
    for name in ('dma','tpu'):
        result=result.replace('accept && '+name+'_address',name+'_local_accept')
    restored=result.replace(WIRES,'')
    for name in ('dma','tpu'):
        restored=restored.replace(name+'_local_accept','accept && '+name+'_address')
    assert restored==source
    return result


def prove_local(out):
    folder=out/'local-proof';folder.mkdir(exist_ok=False)
    source=ROOT/'build-ddr-boot-first-branch/synapse32_dram_soc.sv'
    text=source.read_text();patch_local(text)
    required=[r'    wire external_address = [^;]+;',r'    wire dma_address = [^;]+;',
              r'    wire tpu_address = [^;]+;',r'    assign req_ready = [^;]+;',r'    wire accept = [^;]+;']
    declarations='\n'.join(re.search(p,text)[0] for p in required)
    harness='''module proof(input rst,idle,req_valid,ext_req_ready,input [31:0] req_addr,output same);
wire req_ready;
'''+declarations+'\n'+WIRES+'''
assign same = (dma_local_accept == (accept && dma_address)) &&
              (tpu_local_accept == (accept && tpu_address));
endmodule
'''
    for name in ['synapse32_dram_soc.sv','synapse32_dram_soc_synth.sv']:
        assert WIRES in (out/name).read_text()
    (folder/'proof.v').write_text(harness)
    ys=folder/'proof.ys';ys.write_text(f'read_verilog {folder/"proof.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -prove same 1 -verify\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (folder/'proof.log').open('w') as log:
        rc=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT).returncode
    assert rc==0,folder/'proof.log'
    paths=[source,out/'synapse32_dram_soc.sv',out/'synapse32_dram_soc_synth.sv',Path(__file__).resolve(),yosys,folder/'proof.v',ys,folder/'proof.log',out/'prepared.json']
    (folder/'results.json').write_text(json.dumps(dict(passed=True,
        claim='Actual DMA/TPU acceptance predicates are identical for every 32-bit address, reset, idle, request-valid and external-ready value. No address, handshake, reset or side-effect exception. Remaining SoC text is unchanged by this patch.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS exact local DMA/TPU acceptance for all addresses and controls',flush=True)
