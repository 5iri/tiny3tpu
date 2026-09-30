"""Read-only inventory of the retained chip database's raw timing bounds."""
import hashlib,json,mmap,struct
from pathlib import Path
p=Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin')
f=p.open('rb'); b=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
def i(o):
 assert 0<=o<=len(b)-4
 return struct.unpack_from('<i',b,o)[0]
def ptr(o):
 v=o+4*i(o);assert 0<=v<len(b);return v
def string(o):
 v=ptr(o);return b[v:b.find(b'\0',v)].decode()
def stats(pairs):
 assert all(0<=lo<=hi for lo,hi in pairs)
 return dict(count=len(pairs),distinct_bounds=sum(lo!=hi for lo,hi in pairs),zero_minimum=sum(lo==0 for lo,hi in pairs),minimum_ps=min((lo for lo,hi in pairs),default=None),maximum_ps=max((hi for lo,hi in pairs),default=None))
c=ptr(0);assert i(c+8)==1
t=ptr(c+52);nt,nw,np=(i(t+x) for x in (0,4,8));assert 0<=nt<10000 and 0<nw<100000 and 0<np<1000000
pip=ptr(t+20); pp=[(i(pip+20*j+4),i(pip+20*j+8)) for j in range(np)]
cp=[];tiles=ptr(t+12)
for n in range(nt):
 tile=tiles+n*12; ni=i(tile+4);instances=ptr(tile+8)
 for j in range(ni):
  instance=instances+j*12;nv=i(instance+4);variants=ptr(instance+8)
  for k in range(nv):
   variant=variants+k*20;nd=i(variant+4);delays=ptr(variant+12)
   cp.extend((i(delays+d*16+8),i(delays+d*16+12)) for d in range(nd))
r=dict(device=string(c),generator=string(c+4),speed_grade_count=i(c+48),timed_tile_types=nt,wire_classes=nw,pip_bounds=stats(pp),cell_bounds=stats(cp),scope='Raw database field inventory. Distinct numbers do not establish provenance, speed-grade applicability, or valid physical corner bounds.',physical_hold_analysis_ready=False,full_soc_timing_accepted=False,sha256={str(p):hashlib.sha256(b).hexdigest(),str(Path(__file__).resolve()):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
out=Path(__file__).resolve().parents[1]/'build-grade2-chipdb-delay-bounds';out.mkdir(exist_ok=False);(out/'report.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
