#!/usr/bin/env python3
"""Route a fixed stock-column layout and compare after constant-pin routing fixup."""
import argparse,copy,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--moves',type=Path)
    p.add_argument('--patch',type=Path,required=True)
    a=p.parse_args();cp=a.checkpoint.resolve();out=a.out.resolve();assert not out.exists()
    manifest=cp/'manifest.json';checkpoint=json.loads(manifest.read_text())
    assert checkpoint['passed'] and all(checkpoint[k] for k in ['routed_json_exact','timing_graph_exact','native_fmax_exact','inputs_unchanged'])
    for key in ['sha256','output_sha256']:
        for n,h in checkpoint[key].items():assert digest(n)==h,n
    parent=Path(checkpoint['parent']);record=json.loads(parent.read_text())
    for key in ['sha256','output_sha256']:
        for n,h in record[key].items():assert digest(n)==h,n
    source=cp/'pre-fixup.json';reference=parent.parent/'routed.json'
    gold=json.loads(source.read_text());original=json.loads(reference.read_text())
    from synapse32_packed_write_id_guard import apply_verified
    patch=json.loads(a.patch.read_text());assert patch['passed'] and patch['checkpoint']==str(manifest)
    for n,h in patch['sha256'].items():assert digest(n)==h,n
    gold=apply_verified(patch,gold)
    gate=copy.deepcopy(gold)
    cells=gate['modules']['top']['cells'];before=original['modules']['top']['cells'];assert set(cells)==set(before)|set(patch['added_cells'])
    assert a.moves is None;requested=patch['placements'];assert isinstance(requested,dict)
    assert set(requested)<=set(cells)
    changes={}
    for n,c in cells.items():
        old=before[n]['attributes']['NEXTPNR_BEL'] if n in before else None;new=requested.get(n,old)
        assert isinstance(new,str) and '/' in new
        c['attributes']['NEXTPNR_BEL']=new;c['attributes']['BEL_STRENGTH']=format(5,'032b')
        if old is not None and new!=old:changes[n]=[old,new]
    bels=[c['attributes']['NEXTPNR_BEL'] for c in cells.values()];assert len(bels)==len(set(bels))
    for m in gate['modules'].values():
        m['settings']['placer']='sa';m['settings']['placer1/startTemp']='0.000000'
        for net in m['netnames'].values():net.get('attributes',{}).pop('ROUTING',None)
    restored=copy.deepcopy(gate)
    for mn,m in restored['modules'].items():
        m['settings']=gold['modules'][mn]['settings']
        for n,c in m['cells'].items():c['attributes']=gold['modules'][mn]['cells'][n]['attributes']
        for n,net in m['netnames'].items():net['attributes']=gold['modules'][mn]['netnames'][n]['attributes']
    assert restored==gold
    derived=record['timing']['derived_clocks'];assert set(derived)<=set(gate['modules']['top']['netnames'])
    out.mkdir();inp=out/'input.json';inp.write_text(json.dumps(gate,separators=(',',':'))+'\n')
    cmd=record['command'].copy()
    tool=Path('/tmp/tiny3tpu-nextpnr-pinmap-preservation/nextpnr-xilinx').resolve();build_path=tool.with_name('build-manifest.json');build=json.loads(build_path.read_text())
    assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
    for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
    control_path=Path(__file__).resolve().parents[1]/'build-pinmap-enabled-fixed-replay/control-integrity.json';control=json.loads(control_path.read_text());assert control['passed'] and control['logical_cells_exact'] and control['all_logical_inputs_present']
    for n,h in control['sha256'].items():assert digest(n)==h,n
    for r in control['checked_manifests']:assert digest(r['path'])==r['sha256']
    cmd[0]=str(tool)
    xdc_source=Path(cmd[cmd.index('--xdc')+1]);xdc=out/'restored-clocks.xdc'
    suffix='\n# Exact parent derived clocks restored for --no-pack; no period changes.\n'
    for name,v in sorted(derived.items()):suffix+=f'create_clock -period {1000/v["mhz"]:.12f} [get_nets "{name}"]\n'
    xdc.write_text(xdc_source.read_text()+suffix)
    for flag,v in [('--json',inp),('--xdc',xdc),('--write',out/'routed.json'),('--log',out/'route.log'),('--report',out/'report.json')]:cmd[cmd.index(flag)+1]=str(v)
    cmd+=['--no-pack','--placer','sa','--starttemp','0']
    assert not any(x in cmd for x in ['--force','--timing-allow-fail','--ignore-loops','--no-place','--fasm'])
    paths=[manifest,parent,source,reference,inp,xdc,xdc_source,Path(__file__).resolve(),Path(__file__).with_name('synapse32_packed_equivalence.py').resolve(),Path(__file__).with_name('synapse32_pinmap_control_audit.py').resolve(),tool,build_path,control_path]
    paths.extend([a.patch.resolve(),Path(__file__).with_name('synapse32_packed_write_id_guard.py').resolve()])
    if a.moves:paths.append(a.moves.resolve())
    hashes=dict(record['sha256']);hashes.update({str(q):digest(q) for q in paths})
    result=dict(passed=False,parent=str(parent),checkpoint=str(manifest),command=cmd,sha256=hashes,requested_placement_changes=changes,new_cell_placements={n:requested[n] for n in patch['added_cells']},input_logic_exact=False,patch=str(a.patch.resolve()),input_logic_equivalent=True,restored_parent_derived_clocks=derived,scope='Original legality and pin fixup run with every cell fixed to the parent final BEL except explicitly listed moves. Proved selector/guard/ready/counter edits and eight read-response encoders and a write-ID enable guard and proved added combinational LUTs; no state, cycle, clock period or timing model changes. Full routing and constant-pin fixup precede complete logical-port comparison with shared-pin labels expanded and every LUT/RAM input required; this remains an unqualified timing diagnostic.',full_soc_timing_accepted=False)
    output=out/'manifest.json';output.write_text(json.dumps(result,indent=2)+'\n')
    env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))}
    env.update(NEXTPNR_DUMP_INVALID_TILE='1',TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS='1',TINY3TPU_CARRY_GUIDANCE_PS='100',TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(record['placement_beta']),TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'))
    with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
    result.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()))
    if rc==0:
        actual=json.loads((out/'routed.json').read_text());after=actual['modules']['top']['cells']
        result['cell_set_exact']=set(after)==set(gold['modules']['top']['cells'])
        result['new_placement_exact']=all(after[n]['attributes']['NEXTPNR_BEL']==requested[n] for n in patch['added_cells'])
        moves={n:[before[n]['attributes']['NEXTPNR_BEL'],c['attributes']['NEXTPNR_BEL']] for n,c in after.items() if n in before and before[n]['attributes']['NEXTPNR_BEL']!=c['attributes']['NEXTPNR_BEL']}
        result.update(placement_changes=moves,requested_placement_exact=moves==changes,packed_logic_matches_patch=functional_cells(gold)[0]==functional_cells(actual)[0])
        result['clock_constraints_applied']='matched nothing' not in (out/'route.log').read_text() and 'NOT applied' not in (out/'route.log').read_text()
        result['passed']=result['inputs_unchanged'] and all(result[k] for k in ['cell_set_exact','new_placement_exact','requested_placement_exact','packed_logic_matches_patch','clock_constraints_applied'])
    from synapse32_timing_report import summarize
    result.update(pinmap_preservation_enabled=True,grade_selection=record['grade_selection'],domain_criticality_enabled=True,placement_beta=record['placement_beta'],placement_timing_weight=record['placement_timing_weight'],symbolic_carry_guidance_ps=100)
    result['timing']=summarize((out/'route.log').read_text(),exit_code=rc)
    result['output_sha256']={str(q):digest(q) for q in [out/'routed.json',out/'route.log',out/'report.json',out/'guidance-timing-graph.tsv'] if q.exists()}
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k in ['passed','exit_code','cell_set_exact','requested_placement_exact','packed_logic_matches_patch','clock_constraints_applied']}))
    assert result['passed'],output

if __name__=='__main__':main()
