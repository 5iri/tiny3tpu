"""Require the retimed predicate to terminate only at synchronous same-clock inputs."""
import argparse,collections,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest

def audit(m):
 cs=m['cells'];uses=collections.defaultdict(list)
 for n,c in cs.items():
  for p,bs in c['connections'].items():
   if c['port_directions'][p]=='input':
    for b in bs:uses[b].append((n,p))
 seen={54724};queue=[54724];ends=set()
 while queue:
  b=queue.pop()
  for n,p in uses[b]:
   c=cs[n];kind=c['attributes'].get('X_ORIG_TYPE','')
   if c['type'] in ['SLICE_LUTX','SELMUX2_1','CARRY4']:
    assert kind.startswith('LUT') if c['type']=='SLICE_LUTX' else kind in ['MUXF7','MUXF8','CARRY4']
    for o,bs in c['connections'].items():
     if c['port_directions'][o]=='output':
      for v in bs:
       if v not in seen:seen.add(v);queue.append(v)
   else:
    assert c['type']=='SLICE_FFX' and kind in ['FDRE','FDSE'] and p in ['D','CE','SR']
    assert c['attributes']['X_FFSYNC'].strip()=='1' and c['connections']['CK']==[156059]
    assert c['attributes']['X_ORIG_PORT_SR']==('R' if kind=='FDRE' else 'S')
    ends.add((n,p,kind))
 assert not any(seen&set(p['bits']) for p in m['ports'].values());assert ends
 return dict(reached_bits=len(seen),synchronous_endpoint_ports=len(ends),endpoints=[dict(cell=n,port=p,primitive=k) for n,p,k in sorted(ends)])

def main():
 p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();rp=a.route.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'];source=a.route.resolve()/'input.json';assert record['sha256'][str(source)]==digest(source);m=json.loads(source.read_text())['modules']['top'];result=audit(m);n=result['endpoints'][0]['cell'];old=m['cells'][n]['connections']['CK'];m['cells'][n]['connections']['CK']=[111297]
 try:audit(m)
 except AssertionError:pass
 else:raise AssertionError('accepted cross-clock observer')
 m['cells'][n]['connections']['CK']=old;m['ports']['negative_observer']=dict(direction='output',bits=[54724])
 try:audit(m)
 except AssertionError:pass
 else:raise AssertionError('accepted top-port observer')
 del m['ports']['negative_observer'];assert audit(m)==result
 result.update(passed=True,cross_clock_negative_rejected=True,top_port_negative_rejected=True,scope='Structural same-clock synchronous observer check for predicate retiming; no hold, skew, analog glitch or DDR IO timing signoff.',sha256={str(q.resolve()):digest(q) for q in [rp,source,Path(record['patch']),Path(__file__)]});a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['endpoints','sha256']}))
if __name__=='__main__':main()
