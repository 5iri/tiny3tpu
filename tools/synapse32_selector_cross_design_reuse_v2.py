#!/usr/bin/env python3
"""Route a fixed stock-column layout and compare after constant-pin routing fixup."""
import argparse,copy,json,os,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--moves',type=Path)
    p.add_argument('--reuse-checkpoint',type=Path,required=True)
    a=p.parse_args();assert a.moves is None, 'Use the verified candidate placement without new moves';cp=a.checkpoint.resolve();out=a.out.resolve();assert not out.exists()
    manifest=cp/'manifest.json';checkpoint=json.loads(manifest.read_text())
    assert checkpoint['passed'] and all(checkpoint[k] for k in ['routing_serialization_only_change','timing_graph_exact','native_fmax_exact','inputs_unchanged'])
    for key in ['sha256','output_sha256']:
        for n,h in checkpoint[key].items():assert digest(n)==h,n
    parent=Path(checkpoint['parent']);record=json.loads(parent.read_text())
    for key in ['sha256','output_sha256']:
        for n,h in record[key].items():assert digest(n)==h,n
    source=cp/'pre-fixup.json';reference=parent.parent/'routed.json'
    gold=json.loads(source.read_text());original=json.loads(reference.read_text());assert functional_cells(gold)[0]==functional_cells(original)[0];gate=copy.deepcopy(gold)
    cells=gate['modules']['top']['cells'];before=original['modules']['top']['cells'];assert set(cells)==set(before)
    requested=json.loads(a.moves.read_text()) if a.moves else {};assert isinstance(requested,dict)
    assert set(requested)<=set(cells)
    changes={}
    for n,c in cells.items():
        old=before[n]['attributes']['NEXTPNR_BEL'];new=requested.get(n,old)
        assert isinstance(new,str) and '/' in new
        c['attributes']['NEXTPNR_BEL']=new;c['attributes']['BEL_STRENGTH']=format(5,'032b')
        if new!=old:changes[n]=[old,new]
    bels=[c['attributes']['NEXTPNR_BEL'] for c in cells.values()];assert len(bels)==len(set(bels))
    for m in gate['modules'].values():
        m['settings']['placer']='sa';m['settings']['placer1/startTemp']='0.000000'
        # Keep the checkpoint routing as the original router's starting state.
    reuse_manifest=a.reuse_checkpoint.resolve()/'manifest.json';reuse_check=json.loads(reuse_manifest.read_text())
    assert reuse_check['passed'] and reuse_check['routing_serialization_only_change']
    for key in ['sha256','output_sha256']:
        for n,h in reuse_check[key].items():assert digest(n)==h,n
    reuse_source=reuse_manifest.parent/'pre-fixup.json';reuse_reference=reuse_manifest.parent/'routed.json'
    reuse_design=json.loads(reuse_source.read_text());reuse_final=json.loads(reuse_reference.read_text())
    excluded_bits=set()
    for cell in cells.values():
        for port,bits in cell['connections'].items():
            if 'CLK' in port or port in ('CK','C') or any(k in cell['type'] for k in ['BUFG','PLL','PSEUDO_GND','PSEUDO_VCC']):excluded_bits.update(bits)
    from collections import defaultdict
    def endpoints(module):
        result=defaultdict(set)
        for name,cell in module['cells'].items():
            for port,bits in cell['connections'].items():
                for index,b in enumerate(bits):result[b].add((name,cell['type'],port,index,cell['port_directions'][port],cell['attributes']['NEXTPNR_BEL']))
        return result
    oldmod=reuse_design['modules']['top'];finalmod=reuse_final['modules']['top'];newmod=gate['modules']['top'];oldend=endpoints(oldmod);finalend=endpoints(finalmod);newend=endpoints(newmod)
    changed_sites=set()
    for pair in record['requested_placement_changes'].values():
        changed_sites.update(v.split('/')[0] for v in pair)
    changed_sites.update(v.split('/')[0] for v in record['new_cell_placements'].values())
    halo=set()
    for site in changed_sites:
        match=re.fullmatch(r'SLICE_X(\d+)Y(\d+)',site);assert match
        x,y=map(int,match.groups())
        halo.update(f'SLICE_X{x+dx}Y{y+dy}' for dx in range(-2,3) for dy in range(-2,3) if x+dx>=0 and y+dy>=0)
    locally_released=[]
    incompatible=[];rebuilt_nets=[]
    for name,net in newmod['netnames'].items():
        net.get('attributes',{}).pop('ROUTING',None)
        oldnet=oldmod['netnames'].get(name);finalnet=finalmod['netnames'].get(name)
        if name.startswith('$PACKER_') or set(net['bits'])&excluded_bits:rebuilt_nets.append(name);continue
        if oldnet is None or finalnet is None or len(net['bits'])!=1 or len(oldnet['bits'])!=1 or len(finalnet['bits'])!=1 or oldend[oldnet['bits'][0]]!=newend[net['bits'][0]] or finalend[finalnet['bits'][0]]!=newend[net['bits'][0]]:
            incompatible.append(name);continue
        routing=oldnet.get('attributes',{}).get('ROUTING','')
        if set(re.findall(r'SLICE_X\d+Y\d+',routing))&halo:locally_released.append(name);continue
        if routing.strip():net.setdefault('attributes',{})['ROUTING']=routing
    for net in gate['modules']['top']['netnames'].values():
        value=net.get('attributes',{}).get('ROUTING','')
        if not value.strip():continue
        parts=value.split(';');assert len(parts)%3==0
        for i in range(2,len(parts),3):
            assert 0<=int(parts[i])<=5
            parts[i]=str(max(4,int(parts[i])))
        net['attributes']['ROUTING']=';'.join(parts)
    routed_net_records=sum(bool(v.get('attributes',{}).get('ROUTING','').strip()) for v in gate['modules']['top']['netnames'].values())
    assert routed_net_records>1000
    restored=copy.deepcopy(gate)
    for mn,m in restored['modules'].items():
        m['settings']=gold['modules'][mn]['settings']
        for n,c in m['cells'].items():c['attributes']=gold['modules'][mn]['cells'][n]['attributes']
        for n,net in m['netnames'].items():net['attributes']=gold['modules'][mn]['netnames'][n]['attributes']
    assert restored==gold
    derived=record['restored_parent_derived_clocks'];assert set(derived)<=set(gate['modules']['top']['netnames'])
    out.mkdir();inp=out/'input.json';inp.write_text(json.dumps(gate,separators=(',',':'))+'\n')
    cmd=record['command'].copy()
    tool=Path('/tmp/tiny3tpu-nextpnr-grade2-lossless-checkpoint/nextpnr-xilinx').resolve();build_path=tool.with_name('build-manifest.json');build=json.loads(build_path.read_text())
    assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
    for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
    control_path=Path(__file__).resolve().parents[1]/'build-pinmap-enabled-fixed-replay/control-integrity.json';control=json.loads(control_path.read_text());assert control['passed'] and control['logical_cells_exact'] and control['all_logical_inputs_present']
    for n,h in control['sha256'].items():assert digest(n)==h,n
    for r in control['checked_manifests']:assert digest(r['path'])==r['sha256']
    cmd[0]=str(tool)
    xdc_source=Path(cmd[cmd.index('--xdc')+1]);xdc=out/'restored-clocks.xdc'
    xdc.write_text(xdc_source.read_text())
    for flag,v in [('--json',inp),('--xdc',xdc),('--write',out/'routed.json'),('--log',out/'route.log'),('--report',out/'report.json')]:cmd[cmd.index(flag)+1]=str(v)
    assert '--no-pack' in cmd and '--no-place' not in cmd
    cmd+=['--no-place']
    assert not any(x in cmd for x in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
    paths=[manifest,parent,source,reference,inp,xdc,xdc_source,Path(__file__).resolve(),Path(__file__).with_name('synapse32_packed_equivalence.py').resolve(),Path(__file__).with_name('synapse32_pinmap_control_audit.py').resolve(),tool,build_path,control_path]
    if a.moves:paths.append(a.moves.resolve())
    paths.extend([reuse_manifest,reuse_source,reuse_reference])
    original_cp=Path(record['checkpoint']);original_parent=Path(record['parent']);patch_path=Path(record['patch']);paths.extend([original_cp,original_parent,patch_path])
    hashes=dict(record['sha256']);hashes.update({str(q):digest(q) for q in paths})
    result=dict(passed=False,parent=str(original_parent),checkpoint=str(original_cp),input_checkpoint=str(manifest),reuse_checkpoint=str(reuse_manifest),patch=str(patch_path),input_logic_equivalent=True,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [manifest,reuse_manifest]],new_cell_placements=record['new_cell_placements'],command=cmd,sha256=hashes,requested_placement_changes=record['requested_placement_changes'],input_logic_exact=False,no_new_placement_run=True,placement_legality_source=str(parent),checkpoint_routing_retained=True,compatible_routes_locked=True,local_release_radius=2,local_release_sites=sorted(halo),locally_released_routes=locally_released,routed_net_records=routed_net_records,routing_rebuilt_nets=rebuilt_nets,incompatible_route_nets=incompatible,restored_parent_derived_clocks=derived,scope='Cross-design route reuse: the proved candidate full route supplies placement-legality evidence. Every candidate cell remains at its verified BEL; imported routes must match every physical endpoint and BEL in both the donor checkpoint and final donor design. Already legalized pins are not run through the pre-legalization placer a second time; the original router and pin fixup run. No additional logic, clock period or timing model changes beyond the proved candidate patch. Compatible data routing is imported; dedicated clocks and constants are rebuilt, followed by the original router and constant-pin fixup precede complete logical-port comparison with shared-pin labels expanded and every LUT/RAM input required; this remains an unqualified timing diagnostic.',full_soc_timing_accepted=False)
    output=out/'manifest.json';output.write_text(json.dumps(result,indent=2)+'\n')
    env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))}
    env.update(TINY3TPU_PRESERVE_UNTOUCHED_PIN_MAPS='1',TINY3TPU_CARRY_GUIDANCE_PS='100',TINY3TPU_PRIMITIVE_GUIDANCE='1',TINY3TPU_DOMAIN_CRITICALITY='1',NEXTPNR_PLACER_BETA=str(record['placement_beta']),TINY3TPU_TIMING_GRAPH=str(out/'guidance-timing-graph.tsv'))
    with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
    result.update(exit_code=rc,inputs_unchanged=all(digest(n)==h for n,h in hashes.items()))
    if rc==0:
        actual=json.loads((out/'routed.json').read_text());after=actual['modules']['top']['cells']
        result['cell_set_exact']=set(after)==set(before)
        moves={n:[before[n]['attributes']['NEXTPNR_BEL'],c['attributes']['NEXTPNR_BEL']] for n,c in after.items() if n in before and before[n]['attributes']['NEXTPNR_BEL']!=c['attributes']['NEXTPNR_BEL']}
        assert moves=={}
        baseline=json.loads((original_parent.parent/'routed.json').read_text())['modules']['top']['cells']
        fullmoves={n:[baseline[n]['attributes']['NEXTPNR_BEL'],c['attributes']['NEXTPNR_BEL']] for n,c in after.items() if n in baseline and baseline[n]['attributes']['NEXTPNR_BEL']!=c['attributes']['NEXTPNR_BEL']}
        result.update(placement_changes=fullmoves,requested_placement_exact=fullmoves==record['requested_placement_changes'],packed_logic_matches_patch=functional_cells(gold)[0]==functional_cells(actual)[0],new_placement_exact=all(after[n]['attributes']['NEXTPNR_BEL']==v for n,v in record['new_cell_placements'].items()))
        result['clock_constraints_applied']='matched nothing' not in (out/'route.log').read_text() and 'NOT applied' not in (out/'route.log').read_text()
        result['passed']=result['inputs_unchanged'] and all(result[k] for k in ['cell_set_exact','new_placement_exact','requested_placement_exact','packed_logic_matches_patch','clock_constraints_applied'])
    from synapse32_timing_report import summarize
    result.update(pinmap_preservation_enabled=True,grade_selection=record['grade_selection'],domain_criticality_enabled=True,placement_beta=record['placement_beta'],placement_timing_weight=record['placement_timing_weight'],symbolic_carry_guidance_ps=100)
    result['timing']=summarize((out/'route.log').read_text(),exit_code=rc)
    result['output_sha256']={str(q):digest(q) for q in [out/'routed.json',out/'route.log',out/'report.json',out/'guidance-timing-graph.tsv'] if q.exists()}
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k in ['passed','exit_code','cell_set_exact','requested_placement_exact','packed_logic_matches_patch','clock_constraints_applied']}))
    assert result['passed'],output

if __name__=='__main__':main()
