"""Compose proved DMA terminal expressions with the narrowed capacity counter."""
import importlib.util
from pathlib import Path
import subprocess
import hashlib
import json

HERE = Path(__file__).resolve().parent


def patch_dma(source):
    for name in ('dma-write-last', 'dma-write-short'):
        spec = importlib.util.spec_from_file_location(name, HERE.parent/name/'prepare.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        source = module.patch(source)
    return source


def prove_dma(out):
    root = HERE.parents[3]
    proof = out/'dma-proof'; proof.mkdir(exist_ok=False)
    source = root/'build-ddr-dma-uart-reset/axi_dma_wr.v'
    candidate = out/'axi_dma_wr.v'
    assert candidate.read_text() == patch_dma(source.read_text())
    yosys = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    params = '-set AXI_ADDR_WIDTH 32 -set AXI_ID_WIDTH 1 -set AXIS_ID_WIDTH 1 -set AXIS_DEST_WIDTH 1 -set AXIS_USER_ENABLE 0 -set LEN_WIDTH 16 -set TAG_WIDTH 1'
    script = proof/'full.ys'
    script.write_text(f'''read_verilog {source}
chparam {params} axi_dma_wr
rename axi_dma_wr gold
read_verilog {candidate}
chparam {params} axi_dma_wr
rename axi_dma_wr gate
proc
memory_map
opt
equiv_make gold gate equiv
hierarchy -top equiv
opt_clean
equiv_simple
equiv_induct -seq 5
equiv_status -assert
''')
    with (proof/'full.log').open('w') as log:
        rc = subprocess.run([str(yosys), '-Q', '-T', '-s', str(script)], stdout=log, stderr=subprocess.STDOUT).returncode
    paths = [source,candidate,yosys,script,proof/'full.log',Path(__file__).resolve(),
             HERE.parent/'dma-write-last/prepare.py', HERE.parent/'dma-write-short/prepare.py']
    (proof/'results.json').write_text(json.dumps(dict(passed=rc==0,
        claim='Complete current-profile DMA module equivalence after composing direct initial/decrement last-cycle flags with factored capacity. Counts and all state transitions remain equivalent.',
        sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')
    if rc:
        raise SystemExit('FAIL full DMA equivalence: '+str(proof/'full.log'))
    print('PASS complete DMA module equivalence', flush=True)
