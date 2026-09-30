"""Equivalent narrow descriptor end calculations under the existing length guard."""
import hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OLD=re.compile(r"    wire \[32:0\] tx_end=.*?    wire write_ok=",re.S)
NEW='''    wire [16:0] tx_end_low={1'b0,tx_address[15:0]}+{1'b0,byte_count[15:0]};
    wire [16:0] rx_end_low={1'b0,rx_address[15:0]}+{1'b0,byte_count[15:0]};
    wire [16:0] tx_high_next={1'b0,tx_address[31:16]}+17'd1;
    wire [16:0] rx_high_next={1'b0,rx_address[31:16]}+17'd1;
    wire tx_before_rx = tx_end_low[16] ?
        (tx_high_next < {1'b0,rx_address[31:16]} ||
         (tx_high_next == {1'b0,rx_address[31:16]} && tx_end_low[15:0]<=rx_address[15:0])) :
        (tx_address[31:16] < rx_address[31:16] ||
         (tx_address[31:16] == rx_address[31:16] && tx_end_low[15:0]<=rx_address[15:0]));
    wire rx_before_tx = rx_end_low[16] ?
        (rx_high_next < {1'b0,tx_address[31:16]} ||
         (rx_high_next == {1'b0,tx_address[31:16]} && rx_end_low[15:0]<=tx_address[15:0])) :
        (rx_address[31:16] < tx_address[31:16] ||
         (rx_address[31:16] == tx_address[31:16] && rx_end_low[15:0]<=tx_address[15:0]));
    wire descriptor_valid = byte_count!=0 && byte_count[31:16]==0 && byte_count[2:0]==0 &&
        tx_address[1:0]==0 && rx_address[1:0]==0 &&
        tx_address[31:30]==2'b01 && rx_address[31:30]==2'b01 &&
        (tx_address[29:16]!=14'h3fff || tx_end_low<=17'h10000) &&
        (rx_address[29:16]!=14'h3fff || rx_end_low<=17'h10000) &&
        (tx_before_rx || rx_before_tx);
    wire write_ok='''
def patch_descriptor(s):
 assert len(OLD.findall(s))==1
 return OLD.sub(lambda _:NEW,s)
def prove_descriptor(out):
 source=ROOT/'multi-core/synapse32_axi_dma.sv';candidate=out/'synapse32_axi_dma.sv';old=source.read_text();new=candidate.read_text();assert new==patch_descriptor(old)
 proof=out/'descriptor-proof';proof.mkdir();original=OLD.search(old).group(0).removesuffix('    wire write_ok=');replacement=NEW.removesuffix('    wire write_ok=')
 v=proof/'proof.v';v.write_text('module proof(input [31:0] tx_address,rx_address,byte_count,output same);\n'+original.replace('descriptor_valid','gold_valid')+replacement+'assign same=gold_valid==descriptor_valid;\nendmodule\n')
 yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');ys=proof/'proof.ys';ys.write_text(f'read_verilog {v}\nprep -top proof; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
 with (proof/'proof.log').open('w') as log:subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
 paths=[source,candidate,v,ys,proof/'proof.log',Path(__file__).resolve(),yosys]
 (proof/'results.json').write_text(json.dumps(dict(passed=True,claim='Exact descriptor-valid equivalence for all 96 arbitrary address/length bits, including invalid lengths, overflow, overlapping/adjacent buffers and region boundaries. No transaction or register changes.',sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
 print('PASS all-input descriptor range equivalence',flush=True)
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(exist_ok=False);(out/'synapse32_axi_dma.sv').write_text(patch_descriptor((ROOT/'multi-core/synapse32_axi_dma.sv').read_text()));prove_descriptor(out)
