"""Move 13 unchanged FFs, release incident nets, and retain all other routed nets."""
import argparse,copy,json,os,subprocess,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells
from synapse32_locked_reroute_evidence import routes
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--placement-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();r=a.route.resolve();out=a.out.resolve();assert not out.exists();record=json.loads((r/'manifest.json').read_text());assert record['passed'] and json.loads((r/'iteration-integrity.json').read_text())['passed'];source=r/'pre-fixup.json';assert digest(source)==record['output_sha256'][str(source)];gold=json.loads((r/'routed.json').read_text());gate=json.loads(source.read_text());prior=copy.deepcopy(gate);patch=json.loads(a.placement_patch.read_text());assert patch['passed'];cs=gate['modules']['top']['cells'];normalized=[]
vcc=gate['modules']['top']['netnames']['$PACKER_VCC_NET']['bits'];assert len(vcc)==1
for n,c in cs.items():
 if c['type']=='SLICE_LUTX' and c['attributes'].get('NEXTPNR_BEL','').endswith('6LUT') and c['connections'].get('A6') and not c['attributes'].get('X_ORIG_PORT_A6','').strip():
  assert c['connections']['A6']==vcc and not c['attributes'].get('X_ORIG_PORT_A6','').strip();normalized.append(n);del c['connections']['A6'];del c['port_directions']['A6']
assert normalized and functional_cells(prior)[0]==functional_cells(gate)[0]
moves={n:[c['attributes']['NEXTPNR_BEL'],patch['placements'][n]] for n,c in cs.items() if n in patch['placements'] and c['attributes']['NEXTPNR_BEL']!=patch['placements'][n]};assert len(moves)==13
released_bits=set()
for n,(old,new) in moves.items():
 c=cs[n];assert c['type']=='SLICE_FFX' and c['attributes']['X_ORIG_TYPE']=='FDRE' and c['parameters']=={'INIT':'0'};released_bits.update(b for bs in c['connections'].values() for b in bs);c['attributes']['NEXTPNR_BEL']=new
lut='$abc$216920$auto$blifparse.cc:557:parse_blif$226566'
c=cs[lut];assert c['type']=='SLICE_LUTX' and c['attributes']['X_ORIG_TYPE']=='LUT3' and not c['attributes'].get('CONSTR_PARENT');moves[lut]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X115Y19/A6LUT'];c['attributes']['NEXTPNR_BEL']=moves[lut][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
lut='$abc$216920$auto$blifparse.cc:557:parse_blif$226563'
c=cs[lut];assert c['type']=='SLICE_LUTX' and c['attributes']['X_ORIG_TYPE']=='LUT4' and not c['attributes'].get('CONSTR_PARENT');moves[lut]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X115Y19/C6LUT'];c['attributes']['NEXTPNR_BEL']=moves[lut][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
for suffix,new in [('79172','SLICE_X115Y33/DFF'),('79171','SLICE_X114Y46/DFF'),('76029','SLICE_X120Y50/BFF')]:
 n='$auto$ff.cc:337:slice$'+suffix;c=cs[n];assert c['type']=='SLICE_FFX' and c['attributes']['X_ORIG_TYPE']=='FDRE';moves[n]=[c['attributes']['NEXTPNR_BEL'],new];c['attributes']['NEXTPNR_BEL']=new;released_bits.update(b for bs in c['connections'].values() for b in bs)
n='$abc$216920$auto$blifparse.cc:557:parse_blif$233415';c=cs[n];assert c['type']=='SLICE_LUTX' and c['attributes']['X_ORIG_TYPE']=='LUT2' and not c['attributes'].get('CONSTR_PARENT');moves[n]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X107Y102/D6LUT'];c['attributes']['NEXTPNR_BEL']=moves[n][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
n='$auto$ff.cc:337:slice$68249';c=cs[n];assert c['type']=='SLICE_FFX' and c['attributes']['X_ORIG_TYPE']=='FDRE';moves[n]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X130Y133/DFF'];c['attributes']['NEXTPNR_BEL']=moves[n][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
n=next(n for n in cs if '$233944.' in n and n.endswith('.mux8'));c=cs[n];assert c['type']=='SLICE_LUTX' and not c['attributes'].get('CONSTR_PARENT');moves[n]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X115Y32/D6LUT'];c['attributes']['NEXTPNR_BEL']=moves[n][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
n='$auto$ff.cc:337:slice$79172';moves[n][1]='SLICE_X115Y32/DFF';cs[n]['attributes']['NEXTPNR_BEL']=moves[n][1]
n='$tiny3tpu$ddr_capture_or_233944_early';c=cs[n];assert c['type']=='SLICE_LUTX';moves[n]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X115Y32/C6LUT'];c['attributes']['NEXTPNR_BEL']=moves[n][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
for n,new in [('$tiny3tpu$ddr_capture_or_233974_early','SLICE_X119Y48/A6LUT'),(next(n for n in cs if '$233974.' in n and n.endswith('.mux8')),'SLICE_X119Y48/B6LUT')]:
 c=cs[n];assert c['type']=='SLICE_LUTX' and not c['attributes'].get('CONSTR_PARENT');moves[n]=[c['attributes']['NEXTPNR_BEL'],new];c['attributes']['NEXTPNR_BEL']=new;released_bits.update(b for bs in c['connections'].values() for b in bs)
n='$auto$ff.cc:337:slice$79171';moves[n][1]='SLICE_X119Y48/BFF';cs[n]['attributes']['NEXTPNR_BEL']=moves[n][1]
n='$abc$216920$auto$blifparse.cc:557:parse_blif$217104';c=cs[n];assert c['type']=='SLICE_LUTX' and not c['attributes'].get('CONSTR_PARENT');moves[n]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X113Y78/C6LUT'];c['attributes']['NEXTPNR_BEL']=moves[n][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
for n in ['$abc$216920$auto$blifparse.cc:557:parse_blif$225278','$abc$216920$auto$blifparse.cc:557:parse_blif$225281','$auto$ff.cc:337:slice$105019','$auto$ff.cc:337:slice$105016']:
 c=cs[n];old=c['attributes']['NEXTPNR_BEL'];assert old.startswith('SLICE_X90Y142/');new=old.replace('SLICE_X90Y142/','SLICE_X90Y150/');moves[n]=[old,new];c['attributes']['NEXTPNR_BEL']=new;released_bits.update(b for bs in c['connections'].values() for b in bs)
for n,new in [('$abc$216920$auto$blifparse.cc:557:parse_blif$234308','SLICE_X115Y124/C6LUT'),('$auto$ff.cc:337:slice$66897','SLICE_X115Y124/CFF')]:
 c=cs[n];assert not c['attributes'].get('CONSTR_PARENT');moves[n]=[c['attributes']['NEXTPNR_BEL'],new];c['attributes']['NEXTPNR_BEL']=new;released_bits.update(b for bs in c['connections'].values() for b in bs)
n='$auto$ff.cc:337:slice$68477';c=cs[n];assert c['type']=='SLICE_FFX' and c['attributes']['X_ORIG_TYPE']=='FDRE' and not c['attributes'].get('CONSTR_PARENT');moves[n]=[c['attributes']['NEXTPNR_BEL'],'SLICE_X128Y139/AFF'];c['attributes']['NEXTPNR_BEL']=moves[n][1];released_bits.update(b for bs in c['connections'].values() for b in bs)
for c in cs.values():c['attributes']['BEL_STRENGTH']=format(5,'032b')
assert len({c['attributes']['NEXTPNR_BEL'] for c in cs.values()})==len(cs);assert functional_cells(prior)[0]==functional_cells(gate)[0]==functional_cells(gold)[0]
proof_path=Path('build-grade2-readvalid-arrival-swap-proof/proof.json').resolve();proof=json.loads(proof_path.read_text());assert proof['passed'] and proof['primitive_sat_passed'] and proof['negative_control_passed'] and proof['exhaustive_cases']==256 and proof['added_latency_cycles']==0 and proof['added_cells']==proof['removed_cells']==0
for f,h in proof['sha256'].items():assert digest(f)==h,f
assert Path(proof['source'])==source and set(proof['old'])==set(proof['new']) and len(proof['old'])==2
changes=[]
for n,old in proof['old'].items():
 assert prior['modules']['top']['cells'][n]==old
 new=proof['new'][n];assert set(old)==set(new) and all(old[k]==new[k] for k in old if k!='connections') and set(old['connections'])==set(new['connections'])
 for pin,bits in old['connections'].items():
  if bits!=new['connections'][pin]:
   assert cs[n]['connections'][pin]==bits;changes.append([n,pin,bits,new['connections'][pin]]);released_bits.update(bits);released_bits.update(new['connections'][pin]);cs[n]['connections'][pin]=copy.deepcopy(new['connections'][pin])
assert len(changes)==2
cone_path=Path('build-grade2-reset-control-cone-proof/proof.json').resolve();sat_path=Path('build-grade2-reset-control-primitive-proof/proof.json').resolve();cone=json.loads(cone_path.read_text());sat=json.loads(sat_path.read_text());assert cone['passed'] and sat['passed'] and sat['primitive_sat_passed'] and sat['negative_control_passed']
for evidence in [cone,sat]:
 for f,h in evidence['sha256'].items():assert digest(f)==h,f
assert Path(cone['source'])==source
for n,old in cone['old'].items():assert prior['modules']['top']['cells'][n]==old
for n,new in cone['new_root'].items():
 old=cs[n];released_bits.update(b for bs in old['connections'].values() for b in bs);replacement=copy.deepcopy(new);replacement['attributes']['BEL_STRENGTH']=format(5,'032b');assert replacement['attributes']['NEXTPNR_BEL']==old['attributes']['NEXTPNR_BEL'];cs[n]=replacement;released_bits.update(b for bs in replacement['connections'].values() for b in bs)
candidate_logic=functional_cells(gate)[0]
# Release routes using interconnect in the bounded old-to-new register-bank corridor.
region_tiles=set()
region_bits=set()
for v in gate['modules']['top']['netnames'].values():
 routing=v.get('attributes',{}).get('ROUTING','')
 tiles=set(re.findall(r'(?:INT_[LR]|CLBL[LM]_[LR])_X(\d+)Y(\d+)',routing))
 if any((66<=int(x)<=71 and 58<=int(y)<=80) or (68<=int(x)<=72 and 14<=int(y)<=21) or (68<=int(x)<=70 and 32<=int(y)<=34) or (68<=int(x)<=70 and 45<=int(y)<=47) or (71<=int(x)<=73 and 49<=int(y)<=51) or (64<=int(x)<=66 and 101<=int(y)<=120) or (76<=int(x)<=78 and 132<=int(y)<=134) or (81<=int(x)<=83 and 26<=int(y)<=28) or (70<=int(x)<=72 and 47<=int(y)<=49) or (56<=int(x)<=58 and 141<=int(y)<=151) or (68<=int(x)<=71 and 122<=int(y)<=125) for x,y in tiles):
  region_bits.update(v['bits']);region_tiles.update(tiles)
released_bits.update(region_bits)
released=[];locked=[]
for name,v in gate['modules']['top']['netnames'].items():
 if set(v['bits'])&released_bits:
  v.get('attributes',{}).pop('ROUTING',None);released.append(name);continue
 text=v.get('attributes',{}).get('ROUTING','').strip()
 if text:
  fields=text.split(';');assert len(fields)%3==0
  for i in range(0,len(fields),3):assert not fields[i+1] or fields[i+1].startswith('PIPIDX/');fields[i+2]='4'
  v['attributes']['ROUTING']=';'.join(fields);locked.append(name)
out.mkdir();inp=out/'input.json';inp.write_text(json.dumps(gate,separators=(',',':'))+'\n');cmd=record['command'].copy();cmd[0]='/tmp/tiny3tpu-nextpnr-placement-label-replay/nextpnr-xilinx'
for flag,path in [('--json',inp),('--write',out/'routed.json'),('--report',out/'report.json'),('--log',out/'route.log')]:cmd[cmd.index(flag)+1]=str(path)
assert '--no-place' not in cmd and '--no-route' not in cmd and '--fasm' not in cmd
paths=[cone_path,sat_path,*[Path(f) for f in sat['sha256']],proof_path,*[Path(f) for f in proof['sha256']],source,r/'routed.json',r/'manifest.json',r/'iteration-integrity.json',a.placement_patch.resolve(),inp,Path(cmd[0]),Path(cmd[cmd.index('--chipdb')+1]),Path(cmd[cmd.index('--xdc')+1]),Path(__file__).resolve()];hashes={str(q):digest(q) for q in paths};result=dict(passed=False,source=str(source),command=cmd,normalized_synthetic_a6=normalized,moves=moves,released_net_names=released,retained_net_names=locked,sha256=hashes,regional_release_bits=len(region_bits),logic_proof=str(proof_path),comparison_reference='proved two-cell OR-tree candidate; all other logic unchanged',scope='Zero-cycle OR-tree cut swap, exhaustively and SAT proved, plus retained placements. Normal placement and routing, with routes outside the bounded register-bank corridor locked.',full_soc_timing_accepted=False);manifest=out/'manifest.json';manifest.write_text(json.dumps(result,indent=2)+'\n');env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))};env.update(TINY3TPU_REPLAY_PLACEMENT_LABELS='1',TINY3TPU_LOSSLESS_ROUTE_NAMES='1',NEXTPNR_DUMP_INVALID_TILE='1',TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS='1',TINY3TPU_CARRY_GUIDANCE_PS='100',TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(record['placement_beta']),TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'))
with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
result.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()))
if rc==0:
 actual=json.loads((out/'routed.json').read_text());result['logical_ports_exact']=candidate_logic==functional_cells(actual)[0];ac=actual['modules']['top']['cells'];result['placements_exact']=set(ac)==set(cs) and all(ac[n]['attributes']['NEXTPNR_BEL']==c['attributes']['NEXTPNR_BEL'] for n,c in cs.items());ar=routes(gold['modules']['top']);br=routes(actual['modules']['top']);result['retained_routes_exact']=all(ar[n]==br.get(n) for n in locked if n!='$PACKER_GND_NET');result['ground_additions_only']='$PACKER_GND_NET' not in locked or ar['$PACKER_GND_NET']<=br.get('$PACKER_GND_NET',set());result['normalized_ties_restored']=all(ac[n]['connections'].get('A6')==actual['modules']['top']['netnames']['$PACKER_VCC_NET']['bits'] for n in normalized);result['passed']=all(result[k] for k in ['inputs_unchanged','logical_ports_exact','placements_exact','retained_routes_exact','ground_additions_only','normalized_ties_restored'])
result['output_sha256']={str(q):digest(q) for q in out.iterdir() if q.is_file() and q!=manifest};manifest.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['command','sha256','output_sha256','moves','released_net_names','retained_net_names','normalized_synthetic_a6']}));assert result['passed'],manifest
