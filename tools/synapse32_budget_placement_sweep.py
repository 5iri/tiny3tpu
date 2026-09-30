#!/usr/bin/env python3
"""Route fixed inputs using timing-budget-driven placement; retain strict rejection."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
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
    args = parser.parse_args()
    if args.jobs < 1 or len(set(args.seeds)) != len(args.seeds):
        parser.error('jobs must be positive and seeds unique')
    board = args.board.resolve()
    out = args.out.resolve()
    tool = Path('/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx')
    chipdb = Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin')
    inputs = [tool, chipdb, board/'soc.json', board/'kc705.xdc',
              board/'firmware.hex', board/'synth.ys', Path(__file__).resolve(),
              Path(__file__).with_name('synapse32_timing_report.py').resolve()]
    hashes = {str(path): digest(path) for path in inputs}
    out.mkdir(parents=True, exist_ok=False)
    environment = {k: v for k, v in os.environ.items() if not k.startswith('NEXTPNR_')}
    common = {'sha256': hashes, 'board': str(board), 'seeds': args.seeds,
              'placement_environment': {}, 'placer_budgets': True, 'target_mhz': 100,
              'scope': 'Fixed synthesized netlist, boot image, constraints and tools; seed and timing-budget placement only. Diagnostic timing, not DDR hardware signoff.'}
    (out/'inputs.json').write_text(json.dumps(common, indent=2)+'\n')

    def route(seed):
        dest = out/f'seed-{seed}'
        dest.mkdir()
        command = [str(tool), '--chipdb', str(chipdb), '--xdc', str(board/'kc705.xdc'),
                   '--placer-budgets', '--freq', '100', '--seed', str(seed), '--json', str(board/'soc.json'),
                   '--write', str(dest/'routed.json'), '--report', str(dest/'report.json'),
                   '--log', str(dest/'route.log')]
        record = {'seed': seed, 'command': command, 'sha256': hashes}
        manifest = dest/'manifest.json'
        manifest.write_text(json.dumps(record, indent=2)+'\n')
        with (dest/'console.log').open('w') as log:
            rc = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT).returncode
        log_path = dest/'route.log'
        record['timing'] = summarize(log_path.read_text() if log_path.exists() else '', exit_code=rc)
        record['inputs_unchanged'] = all(digest(p) == sha for p, sha in hashes.items())
        timing = record['timing']
        margins = [c['normalized_margin'] for c in timing['final_clocks'].values()]
        margins += [c['budget_ns']/c['delay_ns']-1 for c in timing['cross_clock_delays']
                    if c.get('delay_ns', 0) > 0 and 'budget_ns' in c]
        record['joint_timing_margin'] = min(margins) if margins and timing['completed'] and record['inputs_unchanged'] else None
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
                              'accepted': result['timing']['accepted']}), flush=True)
            ranked = sorted(results, key=lambda r: r['joint_timing_margin'] if r['joint_timing_margin'] is not None else float('-inf'), reverse=True)
            (out/'results.json').write_text(json.dumps({'inputs': common, 'ranked': ranked}, indent=2)+'\n')


if __name__ == '__main__':
    main()
