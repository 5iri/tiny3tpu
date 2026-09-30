"""Parallel atomic result selection in an isolated four-file CPU overlay."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
ATOMIC = ROOT.parent / 'synapse32/rtl/core_modules/atomic_lsu.v'

def patch(source):
    begin = source.index('    always @(*) begin')
    end = source.index('    always @(posedge clk', begin)
    old = source[begin:end]
    arms = [
        ('AMOSWAP', 'rs2_value_mem'),
        ('AMOADD', 'mem_read_data + rs2_value_mem'),
        ('AMOAND', 'mem_read_data & rs2_value_mem'),
        ('AMOOR', 'mem_read_data | rs2_value_mem'),
        ('AMOXOR', 'mem_read_data ^ rs2_value_mem'),
        ('AMOMAX', '($signed(old_word_signed) >= $signed(rs2_signed)) ? mem_read_data : rs2_value_mem'),
        ('AMOMIN', '($signed(old_word_signed) <= $signed(rs2_signed)) ? mem_read_data : rs2_value_mem'),
        ('AMOMAXU', '(mem_read_data >= rs2_value_mem) ? mem_read_data : rs2_value_mem'),
        ('AMOMINU', '(mem_read_data <= rs2_value_mem) ? mem_read_data : rs2_value_mem')]
    new = '    always @(*) begin\n        case (instr_id_mem)\n'
    new += ''.join(f'            INSTR_{name}_W: atomic_new_word = {expr};\n' for name, expr in arms)
    new += "            default: atomic_new_word = 32'h0;\n        endcase\n    end\n\n"
    result = source.replace(old, new).replace('module atomic_lsu (', 'module atomic_lsu_parallel (')
    assert result.replace(new, old).replace('module atomic_lsu_parallel (', 'module atomic_lsu (') == source
    return result

def prepare(source, out):
    out.mkdir(parents=True, exist_ok=False)
    overlay = out / 'overlay'; overlay.mkdir()
    for path in source.glob('*.v'):
        (overlay / path.name).write_bytes(path.read_bytes())
    gate = patch(ATOMIC.read_text())
    (out/'atomic_lsu_parallel.v').write_text(gate)
    cpu = overlay/'riscv_cpu.v'; original = cpu.read_text()
    old = '    atomic_lsu atomic_lsu_inst0 ('
    new = '    atomic_lsu_parallel atomic_lsu_inst0 ('
    assert original.count(old) == 1
    cpu.write_text(original.replace(old, new)+'\n'+gate)
    assert cpu.read_text()[:-len('\n'+gate)].replace(new, old) == original
    return overlay
