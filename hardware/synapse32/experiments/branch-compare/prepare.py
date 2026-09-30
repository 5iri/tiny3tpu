"""Capture branch comparison flags alongside the existing operand registers."""
from pathlib import Path

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
NEW = '''wire branch_equal, branch_signed_less, branch_unsigned_less;
generate if (SYSTEM_MUL) begin : system_operands
    reg [31:0] a_q,b_q;
    reg equal_q, signed_less_q, unsigned_less_q;
    always @(posedge system_clk) begin
        if(system_rst) begin
            a_q<=0;b_q<=0;
            equal_q<=1;signed_less_q<=0;unsigned_less_q<=0;
        end else begin
            a_q<=rs1_raw;b_q<=rs2_raw;
            equal_q <= rs1_raw == rs2_raw;
            signed_less_q <= $signed(rs1_raw) < $signed(rs2_raw);
            unsigned_less_q <= rs1_raw < rs2_raw;
        end
    end
    assign rs1_value=a_q;
    assign rs2_value=b_q;
    assign branch_equal=equal_q;
    assign branch_signed_less=signed_less_q;
    assign branch_unsigned_less=unsigned_less_q;
end else begin : direct_operands
    assign rs1_value=rs1_raw;
    assign rs2_value=rs2_raw;
    assign branch_equal=rs1_value == rs2_value;
    assign branch_signed_less=$signed(rs1_value) < $signed(rs2_value);
    assign branch_unsigned_less=rs1_value < rs2_value;
end endgenerate'''
REPLACEMENTS = {
    '(rs1_value == rs2_value)': '(branch_equal)',
    '(rs1_value != rs2_value)': '(!branch_equal)',
    '($signed(rs1_value) < $signed(rs2_value))': '(branch_signed_less)',
    '($signed(rs1_value) >= $signed(rs2_value))': '(!branch_signed_less)',
    '(rs1_value < rs2_value)': '(branch_unsigned_less)',
    '(rs1_value >= rs2_value)': '(!branch_unsigned_less)'}

def prepare(source, out):
    out.mkdir(parents=True,exist_ok=False);overlay=out/'overlay';overlay.mkdir()
    for path in source.glob('*.v'):(overlay/path.name).write_bytes(path.read_bytes())
    path=overlay/'execution_unit.v';old=path.read_text()
    assert old.count(OLD)==1
    begin=old.index("            7'b1100011: begin // Branch instructions")
    end=old.index("            7'b1101111: begin // JAL",begin)
    body=old[begin:end];changed=body
    for a,b in REPLACEMENTS.items():
        assert changed.count(a)==1;changed=changed.replace(a,b)
    result=old.replace(OLD,NEW).replace(body,changed)
    assert result.replace(NEW,OLD).replace(changed,body)==old
    path.write_text(result);return overlay
