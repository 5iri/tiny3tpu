#!/usr/bin/env python3
"""Build a no-DDR inference image with software and hardware exponential modes."""
import argparse,json,subprocess,sys
from dataclasses import replace
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.program import compile_stablehlo,CompileOptions,KC705,KC705_CORDIC

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'build-showcase/board');a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 records=[];fixture=[]
 for mode,name,symbol,target in [(0,'quantized_mlp','mlp',KC705),(1,'attention_block','attention_sw',KC705),(2,'attention_block','attention_hw',KC705_CORDIC),(3,'banana','banana',KC705)]:
  d=ROOT/'build-showcase'/name
  report=compile_stablehlo(d/'program.mlirbc',out/(symbol+'.h'),CompileOptions(target=target,symbol=symbol,math_mode='freestanding',allow_approximation=True))
  (out/(symbol+'-report.json')).write_text(json.dumps(report,indent=2)+'\n')
  if mode<2 or mode==3:
   data=np.load(d/'input.npy');fixture.append(f'static const float input_{mode}[]={{'+','.join(float(v).hex()+'f' for v in data.ravel())+'};')
  records.append(dict(mode=mode,name=name,symbol=symbol,target=target.name,words=report['signature']['outputs'][0]['bytes']//4))
 (out/'fixture.h').write_text('\n'.join(fixture)+'\n');(out/'modes.json').write_text(json.dumps(records,indent=2)+'\n')
 print('Prepared headers for',records)
if __name__=='__main__':main()
