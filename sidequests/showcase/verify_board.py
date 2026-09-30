#!/usr/bin/env python3
"""Diagnostic-only native reference checks; the live viewer runs no model math."""
import argparse,hashlib,json,sys,time
from pathlib import Path
import numpy as np
import serial
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(Path(__file__).parent)]
from protocol import transact
from test_stablehlo_compiler import Compiled
from tools.program import CompileOptions,KC705

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',type=Path,required=True);p.add_argument('--port',default='/dev/cu.usbserial-0001');a=p.parse_args();out=a.board.resolve()
 banana=Compiled((ROOT/'build-showcase/banana/program.mlirbc').read_bytes(),CompileOptions(target=KC705,math_mode='freestanding',allow_approximation=True));angle=np.zeros(1,np.float32)
 records=[]
 try:
  with serial.Serial(a.port,921600,timeout=1,write_timeout=5) as uart:
   uart.reset_input_buffer()
   cases=[(0,1),(1,1),(2,1),(3,1),(0,3),(1,3),(2,3),(3,2),(99,1),(0,0)]
   for seq,(mode,repeats) in enumerate(cases):
    rec,actual=transact(uart,seq,mode,repeats)
    if mode>3 or repeats<1:
     assert rec['status']==-1 and rec['words']==0 and rec['backend_calls']==0
     rec['rejected_invalid_request']=True
    else:
     assert rec['status']==0
     if mode==3:
      for _ in range(repeats):
       status,outputs=banana.run(angle);assert status==0;expected=outputs[0];angle=np.array([expected[0]],np.float32)
     else:expected=np.load(ROOT/'build-showcase'/('quantized_mlp' if mode==0 else 'attention_block')/'expected-native.npy').ravel()
     np.testing.assert_array_equal(actual.view(np.uint32),expected.ravel().view(np.uint32))
     assert rec['backend_calls']==repeats*(2 if mode==0 else 1 if mode==3 else 6)
     rec['all_words_bit_exact']=True;rec['repeats']=repeats;rec['per_run_ms']=rec['compute_ms']/repeats
    records.append(rec);print(json.dumps(rec),flush=True)
 finally:banana.close()
 report=dict(passed=True,timestamp=time.time(),checks=records,clock_hz=100000000,bitstream_sha256=hashlib.sha256((out/'soc.bit').read_bytes()).hexdigest(),scope='Physical KC705 outputs vs independent native generated C; synthetic inference fixtures and resident banana state. Not full language-model inference.')
 (out/'physical-check.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
