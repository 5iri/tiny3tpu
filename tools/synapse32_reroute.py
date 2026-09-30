#!/usr/bin/env python3
"""Strip only routing from a recorded placed design and reroute at 100 MHz."""
import argparse,copy,hashlib,json,os,subprocess
from pathlib import Path
from synapse32_packed_equivalence import verify_packed_logic
from synapse32_reset_copy_equivalence import collapse_reset_copy
from synapse32_timing_report import summarize, FINAL_CLOCKS, DERIVED_CLOCKS
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int,required=True)
p.add_argument('--checkpoint',type=Path,help='Verified pre-routing placed.json with adjacent manifest.json')
p.add_argument('--estimate-weight',type=float,help='Router2 A* estimate weighting (tool default 1.75)')
p.add_argument('--bias-cost',type=float,help='Router2 center bias cost (tool default 0.25)')
p.add_argument('--router-binary',type=Path,help='Isolated router binary with verified adjacent build-manifest.json')
a=p.parse_args();digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
if a.estimate_weight is not None and not 0.1<=a.estimate_weight<=3: p.error('estimate weight must be in [0.1,3]')
if a.bias_cost is not None and not 0<=a.bias_cost<=2:p.error('bias cost must be in [0,2]')
parent=a.parent.resolve();r=json.loads(parent.read_text())
for n,s in r['sha256'].items():
    if digest(n)!=s:raise SystemExit('Stale input: '+n)
assert r['timing']['completed'] and r['inputs_unchanged']
cmd=list(r['command']);source=Path(cmd[cmd.index('--write')+1])
router_manifest=None
if a.router_binary:
    binary=a.router_binary.resolve();router_manifest=binary.with_name('build-manifest.json')
    rb=json.loads(router_manifest.read_text())
    assert rb['passed'] and rb['baseline_unchanged'] and rb['tool_sha256']==digest(binary)
    for n,s in rb['baseline_sha256'].items():assert digest(n)==s,n
    assert digest(binary.with_name('router2.cc'))==rb['source_sha256']
    assert digest(binary.with_name('router2.patch'))==rb['patch_sha256']
    assert digest(binary.with_name('router2.o'))==rb['object_sha256']
    cmd[0]=str(binary)
checkpoint_manifest=None
if a.checkpoint:
    source=a.checkpoint.resolve();checkpoint_manifest=source.with_name('manifest.json')
    cp=json.loads(checkpoint_manifest.read_text())
    assert cp['parent']==str(parent) and cp['exit_code']==0 and cp['inputs_unchanged']
    assert cp['shared_cells']>=0.95*cp['checkpoint_cells']
    if cp['placement_changes']:
        assert cp.get('passed') and cp.get('legal_placement_verified') and cp.get('packed_logic_unchanged')
        assert cp['requested_placement_exact'] and cp['placement_changes']==cp['requested_placement_changes']
        assert '--no-route' in cp['command'] and '--no-place' not in cp['command']
        assert not any(x in cp['command'] for x in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
        assert cp['input_logic_exact']
        # Recheck all logical cells against the verified original checkpoint.
        parent_netlist=Path(cp['original_checkpoint'])
        assert digest(parent_netlist)==cp['sha256'][str(parent_netlist)]
        candidate_logic=json.loads(source.read_text())
        if cp.get('reset_replication'):candidate_logic=collapse_reset_copy(candidate_logic,cp['reset_replication'])
        assert verify_packed_logic(json.loads(parent_netlist.read_text()),candidate_logic)
    assert cp['placed_sha256']==digest(source)
    for n,s in cp['sha256'].items():assert digest(n)==s,n
gold=json.loads(source.read_text());gate=copy.deepcopy(gold)
removed={}
for mn,m in gate['modules'].items():
    for name,net in m.get('netnames',{}).items():
        if 'ROUTING' in net.get('attributes',{}):removed[(mn,name)]=net['attributes'].pop('ROUTING')
assert removed
check=copy.deepcopy(gate)
for (mn,name),value in removed.items():check['modules'][mn]['netnames'][name]['attributes']['ROUTING']=value
assert check==gold,'Only routing attributes may change'
placements={name:cell.get('attributes',{}).get('NEXTPNR_BEL') for m in gold['modules'].values() for name,cell in m.get('cells',{}).items()}
assert placements and all(placements.values())
routing_settings={}
if a.estimate_weight is not None:routing_settings['router2/estimateWeight']=str(a.estimate_weight)
if a.bias_cost is not None:routing_settings['router2/biasCostFactor']=str(a.bias_cost)
assert len(gate['modules'])==1
module_name=next(iter(gate['modules']))
if routing_settings:
    gate['modules'][module_name].setdefault('settings',{}).update(routing_settings)
    audit=copy.deepcopy(gate)
    if 'settings' in gold['modules'][module_name]:audit['modules'][module_name]['settings']=gold['modules'][module_name]['settings']
    else:del audit['modules'][module_name]['settings']
    for (mn,name),value in removed.items():audit['modules'][mn]['netnames'][name]['attributes']['ROUTING']=value
    assert audit==gold,'Only routing attributes/settings may change'
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);netlist=out/'placed.json';netlist.write_text(json.dumps(gate,separators=(',',':'))+'\n')
# --no-pack skips nextpnr's PLL/buffer clock derivation. Restore the exact
# periods from the parent derivation, whose packed clock tree is unchanged.
derived=r['timing']['derived_clocks']
for name,mhz in DERIVED_CLOCKS.items():assert derived[name]['mhz']==mhz
aliases={n for m in gold['modules'].values() for n in m.get('netnames',{})}
assert set(derived)<=aliases
clock_cells={n:c for m in gold['modules'].values() for n,c in m.get('cells',{}).items() if 'PLL' in c['type'] or 'BUFG' in c['type']}
assert clock_cells['soc.clock_enable.cpu_global_clock']['attributes']['X_ORIG_TYPE']=='BUFGCE'
xdc_source=Path(cmd[cmd.index('--xdc')+1]);xdc=out/'restored-clocks.xdc'
restoration='\n# Exact parent PLL/buffer periods restored for --no-pack reimport.\n'
for name,info in sorted(derived.items()):
    restoration+=f'create_clock -period {1000/info["mhz"]:.12f} [get_nets "{name}"]\n'
xdc.write_text(xdc_source.read_text()+restoration)
cmd[cmd.index('--xdc')+1]=str(xdc)
for flag,value in [('--json',netlist),('--seed',a.seed),('--write',out/'routed.json'),('--report',out/'report.json'),('--log',out/'route.log')]:cmd[cmd.index(flag)+1]=str(value)
cmd+=['--no-pack','--no-place']
assert cmd[cmd.index('--freq')+1]=='100'
assert not any(x in cmd for x in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
sha=dict(r['sha256']);sha.update({str(p):digest(p) for p in [parent,source,netlist,Path(__file__).resolve(),Path(__file__).with_name('synapse32_packed_equivalence.py').resolve(),Path(__file__).with_name('synapse32_reset_copy_equivalence.py').resolve()]})
sha[str(xdc)]=digest(xdc)
if checkpoint_manifest:sha[str(checkpoint_manifest)]=digest(checkpoint_manifest)
if router_manifest:
    sha[str(router_manifest)]=digest(router_manifest)
    sha[str(a.router_binary.resolve())]=digest(a.router_binary)
record={'parent':str(parent),'command':cmd,'seed':a.seed,'sha256':sha,'removed_routing_attributes':len(removed),'input_logic_and_placement_exact':True,'scope':'Same packed cells, placement and firmware; original clock periods restored; routing regenerated with the recorded seed and routing settings.'}
record['checkpoint_placement_changes_from_full_parent']=cp['placement_changes'] if checkpoint_manifest else {}
record['reset_replication']=cp.get('reset_replication') if checkpoint_manifest else None
record['restored_parent_derived_clocks']=derived
record['routing_settings']=routing_settings
record['router_build_manifest']=str(router_manifest) if router_manifest else None
record['clock_restoration_scope']='Original XDC retained verbatim, with explicit identical PLL/buffer periods for clock constraints lost by --no-pack. Same half-period high/low model as original packer; no relaxed clocks or timing exceptions.'
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
env={k:v for k,v in os.environ.items() if not k.startswith('NEXTPNR_')}
with (out/'console.log').open('w') as log:rc=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
record['inputs_unchanged']=all(digest(n)==s for n,s in sha.items())
record['timing']=summarize((out/'route.log').read_text(),exit_code=rc)
log_text=(out/'route.log').read_text()
record['clock_targets_restored']=all(name in record['timing']['final_clocks'] and record['timing']['final_clocks'][name]['target_mhz']==mhz for name,mhz in FINAL_CLOCKS.items()) and 'matched nothing' not in log_text and 'NOT applied' not in log_text
# Keep the raw strict report intact. Its missing-derivation-log reasons remain;
# the actual derivation evidence is separately preserved from the parent run.
record['clock_evidence_note']='Automatic derivation ran in the parent pack, not this --no-pack run. Raw report is unchanged; explicit restored periods and hashed parent provide clock evidence.'
if (out/'routed.json').exists():
    routed=json.loads((out/'routed.json').read_text());after={n:c.get('attributes',{}).get('NEXTPNR_BEL') for m in routed['modules'].values() for n,c in m.get('cells',{}).items()}
    record['placement_changes']={n:[bel,after.get(n)] for n,bel in placements.items() if after.get(n)!=bel}
    record['placement_unchanged']=not record['placement_changes']
    record['recorded_routing_settings']={n:{k:m.get('settings',{}).get(k) for k in routing_settings} for n,m in routed['modules'].items()}
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'clocks':{k:v['mhz'] for k,v in record['timing']['final_clocks'].items()},'inputs_unchanged':record['inputs_unchanged'],'placement_unchanged':record.get('placement_unchanged'),'clock_targets_restored':record['clock_targets_restored'],'completed':record['timing']['completed']}))
