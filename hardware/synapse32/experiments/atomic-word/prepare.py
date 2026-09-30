"""Feed word atomics the forwarded word before load-width selection."""
from pathlib import Path

OLD = '.mem_read_data(mem_read_data_effective),'
NEW = '.mem_read_data(atomic_read_word),'
DECL = '    wire [31:0] atomic_read_word;\n'
ASSIGN = '    assign atomic_read_word = {load_byte3, load_byte2, load_byte1, load_byte0};\n'


def prepare(source, out):
    out.mkdir(parents=True, exist_ok=False)
    overlay = out / 'overlay'
    overlay.mkdir()
    for path in source.glob('*.v'):
        (overlay / path.name).write_bytes(path.read_bytes())
    cpu = overlay / 'riscv_cpu.v'
    reference = cpu.read_text()
    assert reference.count(OLD) == 1
    candidate = reference.replace(OLD, NEW)
    assert candidate.replace(NEW, OLD) == reference
    marker = '    atomic_lsu atomic_lsu_inst0 ('
    anchor = '    reg [7:0] load_byte3;\n'
    assert candidate.count(marker) == candidate.count(anchor) == 1
    candidate = candidate.replace(marker, DECL+marker).replace(anchor, anchor+ASSIGN)
    assert candidate.replace(NEW, OLD).replace(DECL, '').replace(ASSIGN, '') == reference
    cpu.write_text(candidate)
    return overlay
