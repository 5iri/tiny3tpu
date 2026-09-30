"""Share the taken-branch payload after parallel branch-condition selection."""
from pathlib import Path

def branch_body(source):
    begin = source.index("            7'b1100011: begin // Branch instructions")
    end = source.index("            7'b1101111: begin // JAL", begin)
    return source[begin:end]

NEW = """            7'b1100011: begin // Branch instructions
                if (((instr_id == INSTR_BEQ) && (rs1_value == rs2_value)) ||
                    ((instr_id == INSTR_BNE) && (rs1_value != rs2_value)) ||
                    ((instr_id == INSTR_BLT) && ($signed(rs1_value) < $signed(rs2_value))) ||
                    ((instr_id == INSTR_BGE) && ($signed(rs1_value) >= $signed(rs2_value))) ||
                    ((instr_id == INSTR_BLTU) && (rs1_value < rs2_value)) ||
                    ((instr_id == INSTR_BGEU) && (rs1_value >= rs2_value))) begin
                    target_addr = pc_input + imm;
                    jump_signal_comb = 1;
                    jump_addr_comb = target_addr;
                    flush_pipeline_comb = 1;
                    if (target_addr[1:0] != 2'b00) begin
                        trap_to_supervisor_comb = delegate_instr_addr_misaligned;
                        jump_addr_comb = trap_to_supervisor_comb ? stvec : mtvec;
                        instruction_address_misaligned_exception_comb = 1;
                        exception_tval_comb = target_addr;
                    end
                end
            end
"""

def prepare(source, out):
    out.mkdir(parents=True, exist_ok=False)
    overlay = out/'overlay'; overlay.mkdir()
    for path in source.glob('*.v'):
        (overlay/path.name).write_bytes(path.read_bytes())
    path = overlay/'execution_unit.v'; old = path.read_text()
    body = branch_body(old)
    assert old.count(body) == 1
    candidate = old.replace(body, NEW)
    assert candidate.replace(NEW, body) == old
    path.write_text(candidate)
    return overlay
