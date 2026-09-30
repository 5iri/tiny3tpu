"""UART client; consumes board results without executing models on the host."""
import struct,time
import numpy as np

def transact(uart,sequence,mode,repeats=1):
 uart.write(b'IFQ1'+struct.pack('<III',sequence,mode,repeats));uart.flush()
 def exact(n):
  data=bytearray();deadline=time.monotonic()+30
  while len(data)<n:
   data.extend(uart.read(n-len(data)))
   if time.monotonic()>deadline:raise RuntimeError('Inference board response timed out')
  return bytes(data)
 sync=exact(4)
 while sync!=b'IFR1':sync=sync[1:]+exact(1)
 seq,status,cycles,calls,words,checksum=struct.unpack('<IiIIII',exact(24))
 if seq!=sequence or words>613:raise RuntimeError('Bad inference response header')
 raw=exact(words*4);data=np.frombuffer(raw,dtype='<f4').copy()
 got=int(np.bitwise_xor.reduce(data.view(np.uint32))) if words else 0
 if got!=checksum:raise RuntimeError('Inference response checksum mismatch')
 return dict(sequence=seq,mode=mode,status=status,cycles=cycles,compute_ms=cycles/100000.,backend_calls=calls,words=words),data
