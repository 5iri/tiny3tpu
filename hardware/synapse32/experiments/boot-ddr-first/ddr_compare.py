"""Parallel upper-address alternatives for the generated signed burst offsets."""
import hashlib,json,re,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BASE=ROOT/'build-ddr-dma-uart-reset/board/litedram/gateware/kc705_dram.v'

OLD="assign main_litedramnativeportconverter1_addr_changed = (main_litedramnativeportconverter1_cmd_addr[27:4] != main_litedramnativeport1_cmd_payload_addr1[27:4]);"
NEW="""// Compare both native command alternatives before arbitration selection.
(* keep=1 *) wire main_read_addr_changed_parallel = (main_litedramnativeportconverter1_cmd_addr[27:4] != main_read_ar_payload_addr[29:6]);
(* keep=1 *) wire main_write_addr_changed_parallel = (main_litedramnativeportconverter1_cmd_addr[27:4] != main_write_aw_payload_addr[29:6]);
assign main_litedramnativeportconverter1_addr_changed = (main_read_cmd_request && main_read_cmd_grant) ? main_read_addr_changed_parallel :
    ((main_write_cmd_request && main_write_cmd_grant) ? main_write_addr_changed_parallel : (|main_litedramnativeportconverter1_cmd_addr[27:4]));"""

def patch_compare(source):
    assert source.count(OLD)==1
    return source.replace(OLD,NEW)

def prove_compare(out):
    proof=out/'ddr-compare-proof';proof.mkdir(exist_ok=False)
    source=BASE.read_text();patch_compare(source)
    candidate=out/'board/litedram/gateware/kc705_dram.v';actual=candidate.read_text()
    assert actual.count(NEW)==1 and OLD not in actual
    select=re.search(r"always @\(\*\) begin\n    main_litedramnativeport1_cmd_payload_addr1 <= 28'd0;.*?\nend",source,re.S).group(0)
    assert actual.count(select)==1
    harness="""module proof(input [29:0] main_read_ar_payload_addr,main_write_aw_payload_addr,
input [27:0] main_litedramnativeportconverter1_cmd_addr,
input main_read_cmd_request,main_write_cmd_request,main_read_cmd_grant,main_write_cmd_grant,
output same);
reg [27:0] main_litedramnativeport1_cmd_payload_addr1;
wire gold_changed,main_litedramnativeportconverter1_addr_changed;
"""+select+'\n'+OLD.replace('assign main_litedramnativeportconverter1_addr_changed','assign gold_changed')+'\n'+NEW+'\nassign same=(gold_changed==main_litedramnativeportconverter1_addr_changed);\nendmodule\n'
    (proof/'proof.v').write_text(harness)
    ys=proof/'proof.ys';ys.write_text(f'read_verilog {proof/"proof.v"}\nprep -top proof; flatten; opt; check -assert; sat -prove same 1 -verify;\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (proof/'proof.log').open('w') as log:subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True)
    paths=[BASE,candidate,Path(__file__).resolve(),yosys,proof/'proof.v',ys,proof/'proof.log',out/'prepared.json']
    (proof/'results.json').write_text(json.dumps(dict(passed=True,added_latency_cycles=0,
        claim='Exact address-change predicate for all 30-bit read/write addresses, all selected 28-bit addresses, and all request/grant combinations, including both selected and neither selected. Original read priority and default zero address preserved. Only one combinational assignment changes.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS parallel DDR address comparison for every input combination',flush=True)
