"""Move late FIFO enqueue/dequeue control after parallel occupancy predicates."""
from pathlib import Path
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
LEVEL = 'main_write_id_buffer_level'
PUSH = '((main_write_id_buffer_syncfifo_we & main_write_id_buffer_syncfifo_writable) & (~main_write_id_buffer_replace))'
POP = 'main_write_id_buffer_do_read'
OLD = f'''    if ({PUSH}) begin
        if ((~{POP})) begin
            {LEVEL} <= ({LEVEL} + 1'd1);
        end
    end else begin
        if ({POP}) begin
            {LEVEL} <= ({LEVEL} - 1'd1);
        end
    end'''


def new_body():
    lines = ['    // Parallel increment/decrement bit predicates; no control-fed carry chain.']
    for i in range(5):
        if i == 0:
            toggle = f'({PUSH} ^ {POP})'
        else:
            low = f'{LEVEL}[{i-1}:0]'
            toggle = f'(({PUSH} && !{POP} && (&{low})) || (!{PUSH} && {POP} && !(|{low})))'
        lines.append(f'    {LEVEL}[{i}] <= {LEVEL}[{i}] ^ {toggle};')
    return '\n'.join(lines)


def patch_fifo(source):
    assert source.count(OLD) == 1
    assert source.count(f"reg     [4:0] {LEVEL} = 5'd0;") == 1
    assert source.count(f"        {LEVEL} <= 5'd0;") == 1
    return source.replace(OLD, new_body())


def prove_fifo(out):
    root = HERE.parents[3]; proof = out/'fifo-proof'; proof.mkdir(exist_ok=False)
    source = root/'build-ddr-dma-uart-reset/board/litedram/gateware/kc705_dram.v'
    assert OLD in source.read_text()
    ios = 'input sys_clk,sys_rst,main_write_id_buffer_syncfifo_we,main_write_id_buffer_syncfifo_writable,main_write_id_buffer_replace,main_write_id_buffer_do_read'
    modules = []
    for name, body in [('gold', OLD), ('gate', new_body())]:
        modules.append(f'''module {name}({ios}, output reg [4:0] {LEVEL}=0);
always @(posedge sys_clk) begin
{body}
if (sys_rst) {LEVEL} <= 0;
end
endmodule
''')
    connections = ','.join('.'+n+'('+n+')' for n in ['sys_clk','sys_rst','main_write_id_buffer_syncfifo_we',
        'main_write_id_buffer_syncfifo_writable','main_write_id_buffer_replace','main_write_id_buffer_do_read'])
    modules.append(f'''module equiv({ios}, output same);
wire [4:0] g,c;
gold gold({connections}, .{LEVEL}(g));
gate gate({connections}, .{LEVEL}(c));
assign same = g == c;
endmodule
''')
    (proof/'equiv.v').write_text('\n'.join(modules))
    (proof/'proof.ys').write_text(f'read_verilog {proof/"equiv.v"}\nprep -top equiv; flatten; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -prove same 1 -verify;\n')
    yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    with (proof/'proof.log').open('w') as log:
        rc = subprocess.run([str(yosys),'-Q','-T','-s',str(proof/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
    paths = [source, out/'board/litedram/gateware/kc705_dram.v', proof/'equiv.v', proof/'proof.ys', proof/'proof.log', yosys, Path(__file__).resolve()]
    (proof/'results.json').write_text(json.dumps(dict(passed=rc==0,
        claim='Actual five-bit write-ID FIFO occupancy update is cycle-equivalent by induction for arbitrary push/pop/reset, including simultaneous transfers and modular wrap. FIFO payload and pointers unchanged.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    if rc: raise SystemExit('FAIL FIFO occupancy equivalence')
    print('PASS FIFO occupancy temporal induction', flush=True)
