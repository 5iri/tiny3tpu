#!/usr/bin/env python3
"""Prove actual generated timer equivalence and run upstream refresh tests."""
import argparse, hashlib, json, subprocess, sys, unittest
from pathlib import Path
from migen.fhdl import verilog
from generate import patch_refresher
import litedram.core.refresher as refresher
from litedram.modules import MT8JTF12864
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--upstream',type=Path,required=True)
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
periods=sorted(set([1,2,3,8,9, MT8JTF12864(100e6,'1:4').timing_settings.tREFI,100000000]))

def emit(label):
    for period in periods:
        dut=refresher.RefreshTimer(period)
        for signal,name in [(dut.wait,'wait_i'),(dut.done,'done_o'),(dut.count,'count_o')]: signal.name_override=name
        (out/f'{label}_{period}.v').write_text(str(verilog.convert(dut,ios={dut.wait,dut.done,dut.count},name=f'{label}_{period}')))
emit('gold');patch_refresher(out/'evidence');emit('gate')
passed=True
for period in periods:
    width=period.bit_length()
    harness=f'''module equiv(input sys_clk,sys_rst,wait_i,output same);
wire gd,cd; wire [{width-1}:0] gc,cc;
gold_{period} gold(.sys_clk(sys_clk),.sys_rst(sys_rst),.wait_i(wait_i),.done_o(gd),.count_o(gc));
gate_{period} gate(.sys_clk(sys_clk),.sys_rst(sys_rst),.wait_i(wait_i),.done_o(cd),.count_o(cc));
assign same=(gd==cd)&&(gc==cc);
endmodule
'''
    (out/f'harness_{period}.v').write_text(harness)
    script=f'read_verilog {out/f"gold_{period}.v"} {out/f"gate_{period}.v"} {out/f"harness_{period}.v"}\nprep -top equiv; flatten; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -prove same 1 -verify;\n'
    (out/f'proof_{period}.ys').write_text(script)
    with (out/f'proof_{period}.log').open('w') as log:
        rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-s',str(out/f'proof_{period}.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
    passed &= rc==0
sys.path.insert(0,str(a.upstream.resolve()))
from test import test_refresh
with (out/'tests.log').open('w') as log:
    tests=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_refresh))
passed &= tests.wasSuccessful()
paths=[Path(__file__),Path(__file__).with_name('generate.py'),Path(test_refresh.__file__)]
paths += [Path(x) for x in json.loads((out/'evidence/sources.json').read_text())]
paths += list(out.glob('*.v'))+list(out.glob('*.ys'))
(out/'results.json').write_text(json.dumps({'passed':passed,'periods':periods,'tests':tests.testsRun,'claim':'Actual timer count and done identical on every cycle under arbitrary wait/reset, including board refresh and ZQCS periods.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if not passed: raise SystemExit('FAIL: inspect '+str(out))
print('PASS timer temporal induction',periods,'and',tests.testsRun,'upstream refresh tests')
