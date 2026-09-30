"""Capture PHY CSR predicates on the existing CSR address edge, without latency."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT/'build-ddr-dma-uart-reset/board/litedram/gateware/kc705_dram.v'
ADDRESS = 'builder_interface1_adr'
NEXT = ADDRESS+'_wishbone2csr_next_value1'
ENABLE = ADDRESS+'_wishbone2csr_next_value_ce1'
CAPTURE = f'''    if ({ENABLE}) begin
        {ADDRESS} <= {NEXT};
    end'''
DECL = "reg [18:0] phy_csr_address_q = 19'd0;"
EXPR = r"\(builder_csrbank1_sel & \(builder_interface1_bank_bus_adr\[8:0\] == \d+'d(\d+)\)\)"


def capture():
    return CAPTURE[:-len('    end')] + ''.join(
        f"        phy_csr_address_q[{i}] <= ({NEXT} == 14'd{512+i});\n"
        for i in range(19)) + '    end'


def patch_csr(source):
    assert source.count(CAPTURE) == 1
    assert source.count(ADDRESS+' <=') == 1, 'Address reset/extra writer needs a new proof'
    assert source.count("reg    [13:0] builder_interface1_adr = 14'd0;") == 1
    assert 'assign builder_csrbank1_sel = (builder_interface1_bank_bus_adr[13:9] == 1\'d1);' in source
    assert 'assign builder_interface1_bank_bus_adr = builder_adr;' in source
    assert 'assign builder_adr = builder_interface1_adr;' in source
    matches = list(re.finditer(EXPR,source))
    assert len(matches) == 38
    assert sorted(int(m[1]) for m in matches) == sorted(list(range(19))*2)
    result = source.replace(CAPTURE,capture())
    result = result.replace("reg    [13:0] builder_interface1_adr = 14'd0;",
        DECL+'\n'+"reg    [13:0] builder_interface1_adr = 14'd0;")
    result = re.sub(EXPR,lambda m:f'phy_csr_address_q[{int(m[1])}]',result)
    # Only the checked capture block and these exact predicates may change.
    restored = result.replace(DECL+'\n','').replace(capture(),CAPTURE)
    for i in range(19):
        old = next(m[0] for m in matches if int(m[1]) == i)
        restored = restored.replace(f'phy_csr_address_q[{i}]',old)
    assert restored == source
    return result


def prove_csr(out):
    folder = out/'csr-proof';folder.mkdir(exist_ok=False)
    source = BASE.read_text(); patch_csr(source)
    # The generated address has INIT=0, a single enabled writer, and no reset.
    # Check the actual patched candidate also has exactly this capture block.
    candidate = out/'board/litedram/gateware/kc705_dram.v'
    text = candidate.read_text()
    assert text.count(capture()) == 1 and text.count(DECL) == 1
    assert text.count(ADDRESS+' <=') == 1
    assert not re.search(EXPR,text)
    harness = f'''module proof(input sys_clk,input {ENABLE},input [13:0] {NEXT},output same);
reg [13:0] {ADDRESS} = 0;
{DECL}
always @(posedge sys_clk) begin
{capture()}
end
wire [18:0] original;
'''+''.join(f"assign original[{i}] = ({ADDRESS}[13:9] == 5'd1) && ({ADDRESS}[8:0] == 9'd{i});\n" for i in range(19))+'''
assign same = original == phy_csr_address_q;
endmodule
'''
    (folder/'proof.v').write_text(harness)
    ys = folder/'proof.ys'
    ys.write_text(f'read_verilog {folder/"proof.v"}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 3 -tempinduct -maxsteps 12 -prove same 1 -verify\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (folder/'proof.log').open('w') as log:
        rc=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT).returncode
    assert rc == 0, folder/'proof.log'
    paths=[BASE,candidate,Path(__file__).resolve(),yosys,folder/'proof.v',ys,folder/'proof.log',out/'prepared.json']
    (folder/'results.json').write_text(json.dumps(dict(passed=True,
        claim='Temporal induction proves all 19 predecoded PHY addresses equal the original full 14-bit predicates for arbitrary captured addresses and capture enable, including indefinite hold and INIT. Address has no reset; existing access strobes and reset behavior are unchanged. Exactly 38 read/write predicate occurrences change, with no added CSR edge.',
        predicates=19,replacements=38,added_latency_cycles=0,
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS 19 CSR predicates by temporal induction; no added access cycle',flush=True)
