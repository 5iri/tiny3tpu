#!/usr/bin/env python3
"""Route with verified registered-DSP timing coverage; retain strict DDR rejection."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
from synapse32_timing_report import summarize


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[1, 2, 3, 4])
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--tool',type=Path,required=True,help='Isolated DSP timing model binary with build-manifest.json')
    args = parser.parse_args()
    if args.jobs < 1 or len(set(args.seeds)) != len(args.seeds):
        parser.error('jobs must be positive and seeds unique')
    board = args.board.resolve()
    out = args.out.resolve()
    tool = args.tool.resolve()
    build_manifest=tool.with_name('build-manifest.json');build=json.loads(build_manifest.read_text())
    assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
    assert build['timing_model']['passed']
    for n,h in build['baseline_sha256'].items():assert digest(n)==h,n
    for n,k in [('arch.cc','source_sha256'),('arch.patch','patch_sha256'),('arch.o','object_sha256')]:assert digest(tool.with_name(n))==build[k]
    design=json.loads((board/'soc.json').read_text())
    register_params = ('AREG', 'BREG', 'CREG', 'DREG', 'ADREG', 'MREG', 'PREG',
                       'ACASCREG', 'BCASCREG', 'ALUMODEREG', 'CARRYINREG',
                       'CARRYINSELREG', 'INMODEREG', 'OPMODEREG')
    registered={n for m in design['modules'].values() for n,c in m['cells'].items()
                if c['type']=='DSP48E1' and any(int(c['parameters'].get(k,'0'),2) for k in register_params)}

    chipdb = Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin')
    inputs = [tool, chipdb, board/'soc.json', board/'kc705.xdc',
              board/'firmware.hex', board/'synth.ys', Path(__file__).resolve(),
              Path(__file__).with_name('synapse32_timing_report.py').resolve()]
    inputs += [build_manifest]
    hashes = {str(path): digest(path) for path in inputs}
    hashes.update(build['baseline_sha256'])
    out.mkdir(parents=True, exist_ok=False)
    environment = {k: v for k, v in os.environ.items() if not k.startswith('NEXTPNR_')}
    common = {'sha256': hashes, 'board': str(board), 'seeds': args.seeds,
              'placement_environment': {}, 'target_mhz': 100,'expected_registered_dsp_count':len(registered),'dsp_timing_model':build['timing_model'],
              'scope': 'Fixed synthesized netlist, boot image, constraints and tools; seed only. Diagnostic timing, not DDR hardware signoff.'}
    (out/'inputs.json').write_text(json.dumps(common, indent=2)+'\n')

    def route(seed):
        dest = out/f'seed-{seed}'
        dest.mkdir()
        command = [str(tool), '--chipdb', str(chipdb), '--xdc', str(board/'kc705.xdc'),
                   '--freq', '100', '--seed', str(seed), '--json', str(board/'soc.json'),
                   '--write', str(dest/'routed.json'), '--report', str(dest/'report.json'),
                   '--log', str(dest/'route.log')]
        record = {'seed': seed, 'command': command, 'sha256': hashes,'dsp_timing_model':build['timing_model'],'expected_registered_dsp_count':len(registered)}
        manifest = dest/'manifest.json'
        manifest.write_text(json.dumps(record, indent=2)+'\n')
        with (dest/'console.log').open('w') as log:
            rc = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT).returncode
        log_path = dest/'route.log'
        record['timing'] = summarize(log_path.read_text() if log_path.exists() else '', exit_code=rc)
        record['inputs_unchanged'] = all(digest(p) == sha for p, sha in hashes.items())
        covered=re.findall(r'^Info: DSP_PREG_TIMED (.*?) inputs=(\d+) outputs=(\d+) AB_setup=5.89 C_setup=2.11 CLKQ=0.45$',log_path.read_text() if log_path.exists() else '',re.M)
        record['dsp_timing_coverage']={n:{'inputs':int(i),'outputs':int(o)} for n,i,o in covered}
        record['dsp_timing_coverage_verified']=set(record['dsp_timing_coverage'])==registered and all(int(i)>0 and int(o)>0 for n,i,o in covered)
        timing = record['timing']
        margins = [c['normalized_margin'] for c in timing['final_clocks'].values()]
        margins += [c['budget_ns']/c['delay_ns']-1 for c in timing['cross_clock_delays']
                    if c.get('delay_ns', 0) > 0 and 'budget_ns' in c]
        record['partial_joint_timing_margin'] = min(margins) if margins and timing['completed'] and record['inputs_unchanged'] and record['dsp_timing_coverage_verified'] else None
        # DSP coverage alone cannot establish whole-SoC closure. RAMB36,
        # LUTRAM write paths and validated primitive delay bounds are pending.
        record['full_soc_timing_accepted'] = False
        record['joint_timing_margin'] = None
        record['coverage_limitations'] = ['Memory timing coverage and primitive delay validation remain incomplete.']
        manifest.write_text(json.dumps(record, indent=2)+'\n')
        return record

    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(route, seed) for seed in args.seeds]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            clocks = result['timing']['final_clocks']
            print(json.dumps({'seed': result['seed'], 'clocks': {k: v['mhz'] for k, v in clocks.items()},
                              'joint_timing_margin': result['joint_timing_margin'],
                              'accepted': result['timing']['accepted'],'dsp_timing_coverage_verified':result['dsp_timing_coverage_verified']}), flush=True)
            ranked = sorted(results, key=lambda r: r['joint_timing_margin'] if r['joint_timing_margin'] is not None else float('-inf'), reverse=True)
            (out/'results.json').write_text(json.dumps({'inputs': common, 'ranked': ranked}, indent=2)+'\n')


if __name__ == '__main__':
    main()
