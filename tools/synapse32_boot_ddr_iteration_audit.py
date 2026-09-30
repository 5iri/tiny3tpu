#!/usr/bin/env python3
"""Bind proved boot/DMA/DDR edits, unchanged throughput and routed diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','route','sensitivity','check','focused','out'):
        p.add_argument('--'+name, required=True, type=Path)
    a = p.parse_args(); root = Path(__file__).resolve().parents[1]
    candidate = a.candidate.resolve(); records = []

    def check(path):
        path = Path(path).resolve(); data = json.loads(path.read_text())
        count = 0
        for key in ('sha256','output_sha256'):
            for n, h in data.get(key, {}).items():
                assert digest(n) == h, (str(path), n)
                count += 1
        records.append(dict(path=str(path),sha256=digest(path),checked_hashes=count))
        return data

    prepared = check(candidate/'prepared.json'); assert prepared['passed']
    proofs = []
    for relative in ['proof/boot/results.json','proof/results.json','dma-proof/results.json',
                     'fifo-proof/results.json','availability-proof/results.json',
                     'branch-proof/results.json']:
        path = candidate/relative
        if relative == 'proof/boot/results.json' and not path.exists():
            for name in ['synapse32_dram_soc.sv','synapse32_dram_soc_synth.sv',
                         'board/litedram/gateware/kc705_dram.v']:
                assert (candidate/name).read_bytes() == (root/'build-ddr-dma-uart-reset'/name).read_bytes()
            continue
        if relative.startswith(('fifo-','availability-')) and not path.exists(): continue
        if relative == 'branch-proof/results.json' and not path.exists():
            # A changed CPU overlay must never silently escape proof coverage.
            if (candidate/'overlay').exists():
                for src in (root/'build-atomic-word-v2/overlay').glob('*.v'):
                    assert digest(candidate/'overlay'/src.name) == digest(src)
            continue
        proof = check(path); assert proof['passed']; proofs.append(relative)
        if relative == 'branch-proof/results.json':
            assert proof['modes'] == [0, 1]
            cpu = candidate/'overlay/execution_unit.v'
            assert proof['sha256'][str(cpu)] == digest(cpu)
    synthesis = check(candidate/'board/synthesis.json'); assert synthesis['passed']
    functional = []
    for name, parent in [('smoke','build-ddr-dma-uart-reset'),('gemm','build-ddr-gemm-uart-reset')]:
        reference = check(root/parent/'system/results.json')
        actual = check(candidate/name/'results.json')
        assert actual['passed'] and all(actual[k] == reference[k] for k in ('profile','metrics','dma'))
        assert digest(candidate/name/'smoke.bin') == digest(root/parent/'system/smoke.bin')
        functional.append(dict(workload=name,all_profile_metrics_dma_exact=True,
            instructions=actual['profile']['instructions'],cpu_edges=actual['profile']['cpu_edges'],
            cpu_ipc=actual['profile']['cpu_ipc'],system_cycles=actual['metrics']['system_cycles'],
            litedram_frontend_simulated=False))
    for name in ['kc705.xdc','firmware.hex']:
        assert digest(candidate/'board'/name) == digest(root/'build-ddr-dma-uart-reset/board'/name)
    route = check(a.route/'manifest.json')
    assert route['inputs_unchanged'] and route['timing']['completed'] and route['graph_analysis_completed']
    assert route['sha256'][str(candidate/'board/soc.json')] == digest(candidate/'board/soc.json')
    model = check(a.sensitivity/'manifest.json')
    assert model['sha256'][str(a.route.resolve()/'manifest.json')] == digest(a.route/'manifest.json')
    for v in model['variants']:
        path = a.sensitivity/f"graph-pcout-{v['symbolic_pcout_ns']}-carry-{v['symbolic_carry_arc_ns']}.tsv"
        assert digest(path) == v['graph_sha256']
    coverage = check(a.check/'report.json')
    assert coverage['sha256'][str(a.sensitivity.resolve()/'manifest.json')] == digest(a.sensitivity/'manifest.json')
    assert not coverage['accepted'] and not coverage['full_soc_timing_accepted']
    focus = check(a.focused)
    assert focus['sha256'][str(a.sensitivity.resolve()/'manifest.json')] == digest(a.sensitivity/'manifest.json')
    result = dict(passed=True,
        scope='Proof, functional and artifact integrity passed. Timing closure remains rejected; intervals use symbolic missing delays. Workload simulation uses variable-latency memory, while board FIFO changes have separate induction proofs.',
        candidate=str(candidate),route=str(a.route.resolve()),proofs=proofs,functional=functional,
        firmware_identical=True,constraints_identical=True,
        expanded_intervals_ns=[max(x['arrival_ns'] for x in v['maxima']) for v in model['variants']],
        focused_intervals_ns={k:v['worst_ns'] for k,v in focus['results'].items()},
        full_soc_timing_accepted=False,checked_manifests=records,
        sha256={str(Path(__file__).resolve()):digest(__file__)})
    out = a.out.resolve(); assert not out.exists(); out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['passed','expanded_intervals_ns','focused_intervals_ns','full_soc_timing_accepted']}))


if __name__ == '__main__':
    main()
