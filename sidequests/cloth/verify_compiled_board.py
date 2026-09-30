#!/usr/bin/env python3
"""Check physical compiled cloth state against independently executed native C.

The reference is used only for this diagnostic, never to drive the live scene.
Only step/reset commands are sent to the board. All 180 state words and all 84
camera coordinates are compared; physics TPU use must match compiler placement.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
import numpy as np
import serial

ROOT=Path(__file__).resolve().parents[2]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',type=Path,default=ROOT/'build-cloth/compiled-board')
    p.add_argument('--port',default='/dev/cu.usbserial-0001')
    a=p.parse_args();out=a.board.resolve()
    clock_hz=json.loads((out/'application-manifest.json').read_text()).get('clock_hz',100000000)
    subprocess.run(['cc','-shared','-fPIC','-O2','-ffp-contract=off','-I'+str(ROOT/'include'),
                    '-I'+str(out),str(ROOT/'sidequests/cloth/program_check.c'),'-o',str(out/'reference.so')],check=True)
    lib=ctypes.CDLL(str(out/'reference.so'))
    lib.program_advance_float.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    lib.program_advance_float.restype=ctypes.c_int
    lib.program_backend_calls.restype=ctypes.c_uint32
    initial=np.load(ROOT/'build-cloth/stablehlo/input.npy');state=initial.copy()
    camera=json.loads((ROOT/'build-cloth/camera.json').read_text());records=[];total=0
    partitioned=bool(json.loads((out/'compile-report.json').read_text())['partitions'])
    with serial.Serial(a.port,921600,timeout=1,write_timeout=5) as uart:
        uart.reset_input_buffer()
        def exact(n):
            data=bytearray();deadline=time.monotonic()+60
            while len(data)<n:
                data.extend(uart.read(n-len(data)))
                if time.monotonic()>deadline:raise RuntimeError('Board response timeout')
            return bytes(data)
        for sequence,(steps,reset) in enumerate(((1,True),(2,False),(0,True),(1,False))):
            if reset:state=initial.copy();total=0
            before=lib.program_backend_calls()
            assert lib.program_advance_float(state.ctypes.data,steps)==0
            native_calls=lib.program_backend_calls()-before;total+=steps
            uart.write(b'CLQ3'+struct.pack('<II',sequence,steps|512|(256 if reset else 0)));uart.flush()
            sync=exact(4)
            while sync!=b'CLR3':sync=sync[1:]+exact(1)
            got,status,cycles,count,checksum,physics_cycles,sim_steps,calls=struct.unpack('<8I',exact(32))
            assert (got,status,count,sim_steps,calls)==(sequence,0,28,total,native_calls),(got,status,count,sim_steps,calls)
            assert steps==0 or (calls>0)==partitioned,'Physics TPU calls disagree with compiler placement'
            coords=np.frombuffer(exact(84*4),dtype='<i4').reshape(28,3)
            actual=np.frombuffer(exact(180*4),dtype='<u4').reshape(30,6)
            assert np.array_equal(actual,state.view(np.uint32)),f'State bit mismatch at request {sequence}'
            scaled=state[:28,:3]*np.float32(8)
            vertices=np.trunc(scaled+np.where(scaled<0,np.float32(-.5),np.float32(.5))).astype(np.int32)
            expected=vertices@np.array(camera['weights'],np.int32)+np.array(camera['bias'],np.int32)
            assert np.array_equal(coords,expected),f'Transform mismatch at request {sequence}'
            assert int(np.bitwise_xor.reduce(coords.ravel().view(np.uint32)))==checksum
            record=dict(sequence=sequence,steps=steps,reset=reset,state_words_exact=180,
                        coordinate_words_exact=84,physics_tpu_calls=calls,
                        physics_ms=physics_cycles*1000/clock_hz,transform_ms=cycles*1000/clock_hz)
            records.append(record);print(json.dumps(record),flush=True)
    report=dict(passed=True,timestamp=time.time(),checks=records,clock_hz=clock_hz,
                bitstream_sha256=hashlib.sha256((out/'soc.bit').read_bytes()).hexdigest(),
                scope='Physical KC705 state/coordinates bit-exact vs native compiled C; not long-run JAX accuracy')
    (out/'physical-check.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
