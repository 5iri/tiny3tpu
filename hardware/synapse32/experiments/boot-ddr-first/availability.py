"""Remove cascaded occupancy arithmetic from DDR write command availability."""
from pathlib import Path
import hashlib
import json
import subprocess
import fifo

HERE = Path(__file__).resolve().parent
LEVEL = 'main_write_w_buffer_level2'
PUSH = 'main_write_w_buffer_queue'
POP = 'main_write_w_buffer_dequeue'


def substitute(text):
    return text.replace(fifo.PUSH, PUSH).replace(fifo.POP, POP).replace(fifo.LEVEL, LEVEL)


OLD = substitute(fifo.OLD)
NEW = substitute(fifo.new_body())
OLD_COMPARE = 'assign main_write_can_write = (main_write_w_buffer_level1 > main_write_w_buffer_level2);'
COMPARE = '''((main_write_w_buffer_level0 > main_write_w_buffer_level2) ||
    (main_write_w_buffer_readable && main_write_w_buffer_level0 == main_write_w_buffer_level2)) &&
    !(main_write_w_buffer_readable && (&main_write_w_buffer_level0))'''


def patch_availability(source):
    assert source.count(OLD) == 1 and source.count(OLD_COMPARE) == 1
    assert source.count('assign main_write_w_buffer_level1 = (main_write_w_buffer_level0 + main_write_w_buffer_readable);') == 1
    for decl in [f"reg     [4:0] {LEVEL} = 5'd0;", "wire    [4:0] main_write_w_buffer_level1;",
                 "reg     [4:0] main_write_w_buffer_level0 = 5'd0;", f"        {LEVEL} <= 5'd0;"]:
        assert source.count(decl) == 1
    return source.replace(OLD, NEW).replace(OLD_COMPARE,
        '// Include modular overflow even for unreachable FIFO occupancies.\nassign main_write_can_write = '+COMPARE+';')


def prove_availability(out):
    source = HERE.parents[3]/'build-ddr-dma-uart-reset/board/litedram/gateware/kc705_dram.v'
    assert OLD in source.read_text() and OLD_COMPARE in source.read_text()
    proof = out/'availability-proof'; proof.mkdir(exist_ok=False)
    compare = '''module compare(input [4:0] main_write_w_buffer_level0,main_write_w_buffer_level2,
input main_write_w_buffer_readable,output same);
wire [4:0] main_write_w_buffer_level1 = main_write_w_buffer_level0 + main_write_w_buffer_readable;
wire candidate = '''+COMPARE+''';
assign same = candidate == (main_write_w_buffer_level1 > main_write_w_buffer_level2);
endmodule
'''
    (proof/'compare.v').write_text(compare)
    ios = 'input sys_clk,sys_rst,main_write_w_buffer_queue,main_write_w_buffer_dequeue'
    modules = []
    for name, body in [('gold',OLD),('gate',NEW)]:
        modules.append(f'''module {name}({ios}, output reg [4:0] {LEVEL}=0);
always @(posedge sys_clk) begin
{body}
if (sys_rst) {LEVEL} <= 0;
end
endmodule
''')
    conn = '.sys_clk(sys_clk),.sys_rst(sys_rst),.main_write_w_buffer_queue(main_write_w_buffer_queue),.main_write_w_buffer_dequeue(main_write_w_buffer_dequeue)'
    modules.append(f'''module equiv({ios},output same);
wire [4:0] g,c;
gold gold({conn},.{LEVEL}(g));
gate gate({conn},.{LEVEL}(c));
assign same = g == c;
endmodule
''')
    (proof/'counter.v').write_text('\n'.join(modules))
    yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    for name, command in [('compare','sat -prove same 1 -verify'),
                          ('counter','sat -seq 3 -tempinduct -maxsteps 12 -prove same 1 -verify')]:
        top = 'compare' if name == 'compare' else 'equiv'
        script = proof/(name+'.ys'); script.write_text(f'read_verilog {proof/(name+".v")}\nprep -top {top}; flatten; opt; check -assert; {command};\n')
        with (proof/(name+'.log')).open('w') as log:
            rc = subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
        if rc: raise SystemExit('FAIL DDR availability '+name)
    paths = [source,out/'board/litedram/gateware/kc705_dram.v',Path(__file__).resolve(),HERE/'fifo.py',yosys]+list(proof.iterdir())
    (proof/'results.json').write_text(json.dumps(dict(passed=True,
        claim='Availability comparison identical for every pair of five-bit counts and buffered-output flag, including 31+1 overflow. Queued-write counter identical by induction under arbitrary enqueue/dequeue/reset. No extra cycle or traffic restriction.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    print('PASS DDR write availability and queued-count equivalence',flush=True)
