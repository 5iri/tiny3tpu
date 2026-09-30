"""Prove a four-input replacement for a two-LUT reset control cone."""
import copy,hashlib,itertools,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];source=root/'build-grade2-pre-fixup-routing-control/pre-fixup.json';cs=json.loads(source.read_text())['modules']['top']['cells'];names=['$abc$216920$auto$blifparse.cc:557:parse_blif$'+v for v in ['232929','232928']];old={n:cs[n] for n in names};outputs={c['connections']['O6'][0]:n for n,c in old.items()}
def inputs(c):
 result={}
 for pin,bits in c['connections'].items():
  role=c['attributes'].get('X_ORIG_PORT_'+pin,'')
  if role.startswith('I'):
   assert len(bits)==1 and role[1:].isdigit();result[int(role[1:])]=bits[0]
 assert set(result)==set(range(len(result)))
 return result
ins={n:inputs(c) for n,c in old.items()};leaves=sorted({b for v in ins.values() for b in v.values()}-set(outputs));assert len(leaves)==4
rootname=names[-1];rootcell=old[rootname];assert rootcell['type']=='SLICE_LUTX' and not rootcell['attributes'].get('CONSTR_PARENT') and not rootcell['attributes'].get('CONSTR_CHILDREN')
def original(assign):
 memo=dict(assign)
 def bit(b):
  if b not in memo:
   n=outputs[b];index=sum(bit(v)<<i for i,v in ins[n].items());memo[b]=(int(old[n]['parameters']['INIT'],2)>>index)&1
  return memo[b]
 return bit(rootcell['connections']['O6'][0])
init=0;cases=[]
for index in range(16):
 assign={b:(index>>i)&1 for i,b in enumerate(leaves)};value=original(assign);init|=value<<index;cases.append(value)
new=copy.deepcopy(rootcell);new['parameters']={'INIT':format(init,'016b')};new['attributes']={k:v for k,v in new['attributes'].items() if not k.startswith('X_ORIG_PORT_A')};new['attributes']['X_ORIG_TYPE']='LUT4';new['connections']={'O6':rootcell['connections']['O6']};new['port_directions']={'O6':'output'}
for i,b in enumerate(leaves):
 pin=f'A{i+1}';new['connections'][pin]=[b];new['port_directions'][pin]='input';new['attributes']['X_ORIG_PORT_'+pin]=f'I{i}'
ni=inputs(new)
for index in range(16):
 assign={b:(index>>i)&1 for i,b in enumerate(leaves)};actual=(int(new['parameters']['INIT'],2)>>sum(assign[b]<<i for i,b in ni.items()))&1;assert actual==original(assign)
assert (init^1)&1 != cases[0]
out=root/'build-grade2-reset-shared-cone-proof';out.mkdir(exist_ok=False)
r=dict(passed=True,exhaustive_cases=16,negative_control_passed=True,source=str(source),old=old,new_root={rootname:new},leaves=leaves,init_hex=hex(init),added_latency_cycles=0,scope='Exhaustive combinational truth-table proof only. Keep upstream LUTs for other consumers; replace root only. Primitive SAT and placement/routing still pending.',full_soc_timing_accepted=False,sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,Path(__file__).resolve()]});(out/'proof.json').write_text(json.dumps(r,indent=2)+'\n');print({k:r[k] for k in ['passed','exhaustive_cases','init_hex','added_latency_cycles','scope']})
