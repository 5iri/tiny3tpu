"""Bind the retained routed netlist to a readback-checked openXC7 bitstream."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
route=root/'build-grade2-incremental-cq-tpu-output-pairs'
bit=root/'build-grade2-incremental-cq-tpu-output-pairs-bit'
part='xc7k325tffg900-2'
files=[route/'manifest.json',route/'routed.json',route/'evaluation.json',route/'composition-audit.json',bit/'latest.fasm',bit/'latest.frames',bit/'latest.bit',bit/'roundtrip.frames',bit/'export.log',bit/'fasm2frames.log',bit/'frames2bit.log',bit/'bitread.log',root/'build-toolchain-recovery/kc705-frame-db-kc705.tar.gz',Path('/tmp/tiny3tpu-kc705-frame-db/kintex7')/part/'part.yaml',Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin'),Path('/tmp/tiny3tpu-nextpnr-placement-label-replay/nextpnr-xilinx'),Path(__file__).resolve()]
for p in files:assert p.exists() and p.is_file(),p
rm=json.loads((route/'manifest.json').read_text());ev=json.loads((route/'evaluation.json').read_text());co=json.loads((route/'composition-audit.json').read_text());assert rm['passed'] and ev['passed'] and co['passed']
for m in [rm,ev,co]:
 for key in ['sha256','output_sha256']:
  for path,h in m.get(key,{}).items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==h,(path,key)
assert hashlib.sha256(files[-2].read_bytes()).hexdigest()==rm['sha256'][str(files[-2])]
for p in [bit/'export.log',bit/'fasm2frames.log',bit/'frames2bit.log',bit/'bitread.log']:
 assert not any(line for line in p.read_text().lower().splitlines() if 'error' in line and line.strip()!='1 warning, 0 errors'),p
assert 'DONE' in (bit/'bitread.log').read_text()
image=(bit/'latest.bit').read_bytes();assert image.count(bytes.fromhex('aa995566'))==1 and part.encode() in image
expected={}
for line in (bit/'latest.frames').open():
 addr,words=line.split(' ',1);expected[int(addr,16)]=[int(x,16) for x in words.strip().split(',')]
actual={};addr=None;words=[]
for line in (bit/'roundtrip.frames').open():
 if line.startswith('.frame '):
  if addr is not None:actual[addr]=words
  addr=int(line.split()[1],16);words=[]
 elif line.strip():words.extend(int(x,16) for x in line.split())
if addr is not None:actual[addr]=words
assert set(expected)<=set(actual);assert all(len(v)==101 for v in expected.values()) and all(len(v)==101 for v in actual.values())
extra=set(actual)-set(expected)
assert all(all(word==0 for i,word in enumerate(actual[k]) if i!=50) for k in extra)
assert all(all(x==y for i,(x,y) in enumerate(zip(words,actual[k])) if i!=50) for k,words in expected.items())
record=dict(passed=True,part=part,source_route=str(route.relative_to(root)),bitstream=str((bit/'latest.bit').relative_to(root)),size_bytes=len(image),input_frames=len(expected),readback_frames=len(actual),added_zero_data_frames=len(extra),ecc_word_index=50,all_non_ecc_frame_words_exact=True,logic_composition_passed=True,diagnostic_expanded_ns=ev['expanded_intervals_ns'],physical_timing_accepted=False,hardware_tested=False,scope='Open-source bitstream export and frame-data roundtrip only. ECC word is generated during bit assembly. No hardware test, hold/skew/DDR IO closure, or physical 100 MHz proof.',sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
out=bit/'manifest.json';assert not out.exists();out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k!='sha256'},indent=2))
