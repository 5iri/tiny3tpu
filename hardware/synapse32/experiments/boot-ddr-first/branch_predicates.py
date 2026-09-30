"""Compute branch predicates alongside the existing captured operands."""
from pathlib import Path
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = ROOT/'build-atomic-word-v2/overlay/execution_unit.v'
OLD = '''generate if (SYSTEM_MUL) begin : system_operands
    reg [31:0] a_q,b_q;
    always @(posedge system_clk) begin
        if(system_rst) begin a_q<=0;b_q<=0;end
        else begin a_q<=rs1_raw;b_q<=rs2_raw;end
    end
    assign rs1_value=a_q;
    assign rs2_value=b_q;
end else begin : direct_operands
    assign rs1_value=rs1_raw;
    assign rs2_value=rs2_raw;
end endgenerate'''
NEW = '''generate if (SYSTEM_MUL) begin : system_operands
    reg [31:0] a_q,b_q;
    reg equal_q, less_signed_q, less_unsigned_q;
    always @(posedge system_clk) begin
        if(system_rst) begin
            a_q<=0; b_q<=0;
            equal_q<=1; less_signed_q<=0; less_unsigned_q<=0;
        end else begin
            a_q<=rs1_raw; b_q<=rs2_raw;
            equal_q <= rs1_raw == rs2_raw;
            less_signed_q <= $signed(rs1_raw) < $signed(rs2_raw);
            less_unsigned_q <= rs1_raw < rs2_raw;
        end
    end
    assign rs1_value=a_q;
    assign rs2_value=b_q;
    assign branch_equal=equal_q;
    assign branch_less_signed=less_signed_q;
    assign branch_less_unsigned=less_unsigned_q;
end else begin : direct_operands
    assign rs1_value=rs1_raw;
    assign rs2_value=rs2_raw;
    assign branch_equal=rs1_raw == rs2_raw;
    assign branch_less_signed=$signed(rs1_raw) < $signed(rs2_raw);
    assign branch_less_unsigned=rs1_raw < rs2_raw;
end endgenerate'''
PREDICATES = {
    'rs1_value == rs2_value':'branch_equal',
    'rs1_value != rs2_value':'!branch_equal',
    '$signed(rs1_value) < $signed(rs2_value)':'branch_less_signed',
    '$signed(rs1_value) >= $signed(rs2_value)':'!branch_less_signed',
    'rs1_value < rs2_value':'branch_less_unsigned',
    'rs1_value >= rs2_value':'!branch_less_unsigned',
}


def patch_cpu(source):
    assert source.count(OLD) == 1
    replacement = '// Predicates share the existing operand capture edge; branch latency is unchanged.\nwire branch_equal, branch_less_signed, branch_less_unsigned;\n'+NEW
    candidate = source.replace(OLD,replacement)
    for old,new in PREDICATES.items():
        a,b='if ('+old+')','if ('+new+')'
        assert candidate.count(a) == 1
        candidate = candidate.replace(a,b)
    restored = candidate.replace(replacement,OLD)
    for old,new in PREDICATES.items():
        restored = restored.replace('if ('+new+')','if ('+old+')')
    assert restored == source
    return candidate


def prove_branch(out):
    proof=out/'branch-proof';proof.mkdir(exist_ok=False)
    candidate=out/'overlay/execution_unit.v'
    assert candidate.read_text() == patch_cpu(SOURCE.read_text())
    ios='input system_clk,system_rst,input [31:0] rs1_raw,rs2_raw,output [31:0] rs1_value,rs2_value,output branch_equal,branch_less_signed,branch_less_unsigned'
    gold='''assign branch_equal = rs1_value == rs2_value;
assign branch_less_signed = $signed(rs1_value) < $signed(rs2_value);
assign branch_less_unsigned = rs1_value < rs2_value;
'''
    (proof/'capture.v').write_text(f'module gold #(parameter SYSTEM_MUL=1)({ios});\n'+OLD+'\n'+gold+'endmodule\n'+
                                  f'module gate #(parameter SYSTEM_MUL=1)({ios});\n'+NEW+'\nendmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    for mode in (0,1):
        script=proof/f'proof-{mode}.ys'
        script.write_text(f'read_verilog {proof/"capture.v"}\nchparam -set SYSTEM_MUL {mode} gold gate\nproc\nopt\nequiv_make gold gate equiv\nhierarchy -top equiv\nopt_clean\nequiv_simple\nequiv_induct -seq 3\nequiv_status -assert\n')
        with (proof/f'proof-{mode}.log').open('w') as log:
            rc=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
        if rc: raise SystemExit('FAIL branch operand/predicate equivalence, mode '+str(mode))
    paths=[SOURCE,candidate,yosys,Path(__file__).resolve()]+list(proof.iterdir())
    (proof/'results.json').write_text(json.dumps(dict(passed=True,modes=[0,1],
        claim='Actual operand capture and its equality/signed-less/unsigned-less predicates are sequentially equivalent for arbitrary forwarded operand samples and reset in both SYSTEM_MUL modes. Exactly six branch conditions substitute these predicates; all target, trap, flush and output-capture logic remains byte-identical. Existing capture edges and reset values preserved; no added execution stage.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS branch operand/predicate equivalence in both modes',flush=True)
