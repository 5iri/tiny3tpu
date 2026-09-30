#!/usr/bin/env python3
"""Compare exact native transfer traffic and cycles on existing strict 512-bit workload."""
import argparse,importlib.util,json,sys,unittest
from pathlib import Path
from migen import passive
p=argparse.ArgumentParser();p.add_argument('--candidate',action='store_true');p.add_argument('--out',type=Path,required=True);p.add_argument('--upstream',type=Path,required=True)
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);here=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('chosen',(here if a.candidate else here.parent/'dram-write-buffer')/'generate.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.patch_adapter(out/'evidence')
sys.path.insert(0,str(a.upstream.resolve()));sys.path.insert(0,str(here.parent/'dram-command-buffer'))
import width512_test
original=width512_test.run_simulation;records=[]
def observed(dut,generators,*args,**kwargs):
    record={'cycles':0,'commands':0,'write_commands':0,'read_commands':0,'write_beats':0,'read_beats':0}
    @passive
    def monitor():
        port=dut.write_crossbar_port
        while True:
            yield
            record['cycles']+=1
            if (yield port.cmd.valid) and (yield port.cmd.ready):
                record['commands']+=1;record['write_commands' if (yield port.cmd.we) else 'read_commands']+=1
            if (yield port.wdata.valid) and (yield port.wdata.ready):record['write_beats']+=1
            if (yield port.rdata.valid) and (yield port.rdata.ready):record['read_beats']+=1
    result=original(dut,[*generators,monitor()],*args,**kwargs);records.append(record);return result
width512_test.run_simulation=observed
with (out/'tests.log').open('w') as log:
 result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(width512_test.StrictNativeWriteTest))
(out/'results.json').write_text(json.dumps({'passed':result.wasSuccessful(),'candidate':a.candidate,'records':records,'scope':'Fixed strict scheduled-write dependency/masked/burst workload, two read-backpressure settings; not full-SoC cycles.'},indent=2)+'\n')
print(json.dumps(records),flush=True)
if not result.wasSuccessful():raise SystemExit(1)
