#!/usr/bin/env python3
"""Bind fixed-layout routing, complete logical-port equality and expanded timing to parent workloads."""
import gc
gc.disable()  # JSON/netlist trees are acyclic; retain normal reference counting.
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes_v2 import RecoveredHashes
from synapse32_pinmap_control_audit import functional_cells
from synapse32_kc705_grade2_limits import bram_limits,dsp_limits,lutram_limits

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recovery',type=Path,required=True)
    p.add_argument('--legacy-recovery',type=Path,nargs=2,required=True)
    for k in ['route','normalized','sensitivity','check','out']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();recovery=RecoveredHashes(a.recovery,a.legacy_recovery);assert not a.out.exists();seen=set();records=[]
    def verify(path):
        path=path.resolve();d=json.loads(path.read_text())
        if path in seen:return d
        seen.add(path)
        for key in ['sha256','output_sha256','baseline_sha256']:
            for n,h in d.get(key,{}).items():recovery.check(n,h)
        for r in d.get('checked_manifests',[]):recovery.check(r['path'],r['sha256']);verify(Path(r['path']))
        records.append(dict(path=str(path),sha256=digest(path)));return d
    source=verify(a.route/'manifest.json');assert source['passed'] and source['inputs_unchanged'] and source['timing']['completed']
    if source.get('enabled'):
        proof=verify(a.route/'control-integrity.json');assert proof['passed'] and proof['logical_cells_exact'] and proof['placement_exact']
        fixed=verify(Path(source['parent']));changes={}
    else:
        fixed=source;assert fixed['pinmap_preservation_enabled'] and fixed['packed_logic_matches_patch'] and fixed['requested_placement_exact'] and fixed['input_logic_equivalent']
        changes=fixed['requested_placement_changes']
    assert fixed['clock_constraints_applied']
    cp_path=Path(fixed['checkpoint']);cp=verify(cp_path);assert cp['passed']
    parent_path=Path(fixed['parent']);parent=verify(parent_path)
    gold=json.loads((cp_path.parent/'pre-fixup.json').read_text());actual=json.loads((a.route/'routed.json').read_text())
    from synapse32_packed_all_bank_valid_collapse import apply_verified
    patch=verify(Path(fixed['patch']));assert patch['passed'] and patch['checkpoint']==str(cp_path)
    gold=apply_verified(patch,gold)
    assert functional_cells(gold)[0]==functional_cells(actual)[0]
    original=json.loads((parent_path.parent/'routed.json').read_text())['modules']['top']['cells'];cells=actual['modules']['top']['cells'];assert set(original)|set(patch['added_cells'])==set(cells)
    assert source['new_placement_exact'] and all(cells[n]['attributes']['NEXTPNR_BEL']==patch['placements'][n] for n in patch['added_cells'])
    moved={n:[original[n]['attributes']['NEXTPNR_BEL'],c['attributes']['NEXTPNR_BEL']] for n,c in cells.items() if n in original and original[n]['attributes']['NEXTPNR_BEL']!=c['attributes']['NEXTPNR_BEL']};assert moved==changes
    boards=[Path(n) for n in parent['sha256'] if n.endswith('/board/soc.json')];assert len(boards)==1
    candidate=boards[0].parent.parent;prior=verify(candidate/'iteration-integrity.json');assert prior['passed']
    normalized=verify(a.normalized/'manifest.json');assert normalized['passed'] and normalized['source_control']==str((a.route/'manifest.json').resolve()) and normalized['graph_analysis_completed']
    assert digest(a.normalized/'routed.json')==digest(a.route/'routed.json')
    model=verify(a.sensitivity/'manifest.json');assert model['sha256'][str((a.normalized/'manifest.json').resolve())]==digest(a.normalized/'manifest.json')
    data=Path(__file__).resolve().parents[1]/'build-dsp-preg-timing/ds182.txt';expected=dict(bram=bram_limits(data.read_text()),dsp=dsp_limits(data.read_text()),lutram=lutram_limits(data.read_text()));assert model['limits']==json.loads(json.dumps(expected))
    assert model['registered_dsp_count']==4 and model['expected_cascades']==0
    gate=verify(a.check/'report.json');assert not gate['accepted'] and not gate['full_soc_timing_accepted'];assert gate['sha256'][str((a.sensitivity/'manifest.json').resolve())]==digest(a.sensitivity/'manifest.json')
    result=dict(passed=True,recovery=recovery.metadata(),kind='fixed_stock_column_logic_patch',candidate=str(candidate),route=str(a.route.resolve()),normalized=str(a.normalized.resolve()),functional=prior['functional'],new_workload_simulation_run=False,new_rtl_synthesis_run=False,logical_cells_exact=False,logical_cells_match_proved_patch=True,patch=fixed['patch'],placement_changes=moved,new_cell_placements=source['new_cell_placements'],clocks_restored_without_period_changes=True,expanded_intervals_ns=[max(r['arrival_ns'] for r in v['maxima']) for v in model['variants']],native_clocks=source['timing']['final_clocks'],timing_model_category='stock_kc705_registered_primitives',full_soc_timing_accepted=False,scope='Parent actual synthesis/workloads plus exact packed-LUT BDD/SAT equivalence and complete logical-port equality against the proved patch, exact requested BEL moves, original legality and routing checks, restored parent clocks, and independent stock-column timing probes. Selector/guard/ready/counter and eight read-response roots and a write-ID enable guard and main-CE encoder and local AR-ready decode replica and DMA FIFO and transport reset cofactors and three shared UART control LUT collapses, AR control encoding and bankmachine5 valid decode collapse and two exact branch carry/decode cuts and local equivalent data LUT replicas at two unchanged capture FFs change and combinational cofactor LUTs are added; two redundant count flags proved by primitive induction plus exact DSP input-decode LUT collapses and DMA strobe reset cofactoring and exact CPU synchronous-reset LUT collapses, placement-only TPU DSP adjustments, and a DDR control macro encoded as two early LUTs with exact dependency pruning and one late LUT with exact ground-driver provenance and exact valid-decoder collapses for the seven remaining DDR banks; no execution-cycle changes. Clock skew/hold, reset, DDR IO and generic/carry delays remain unvalidated.',checked_manifests=records,sha256={str(q.resolve()):digest(q) for q in [a.recovery,*a.legacy_recovery,Path(__file__).with_name('synapse32_recovered_hashes_v2.py'),Path(__file__).with_name('synapse32_rebuilt_legacy_replay.py'),Path(__file__).with_name('synapse32_recovered_hashes.py'),Path(__file__).with_name('synapse32_rebuilt_toolchain_replay.py'),Path(__file__),Path(__file__).with_name('synapse32_packed_all_bank_valid_collapse.py'),Path(__file__).with_name('synapse32_pinmap_control_audit.py'),Path(__file__).with_name('synapse32_packed_equivalence.py')]})
    a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(passed=True,moved_cells=len(moved),expanded_intervals_ns=result['expanded_intervals_ns'],full_soc_timing_accepted=False)))

if __name__=='__main__':main()
