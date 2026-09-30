#!/usr/bin/env python3
"""Compare checked simulation workloads; never certify a hardware frequency."""
import argparse
import json
import math
from pathlib import Path
import re


def read_metrics(text):
    records = re.findall(r'METRICS (\{[^\n]*\})', text)
    if (len(records) != 1 or text.count('METRICS ') != 1 or
            text.count('PASS Synapse32 variable-latency DRAM -> TPU:') != 1):
        raise ValueError('Require exactly one metrics record and a successful workload')
    data = json.loads(records[0])
    if type(data.get('schema')) is not int or data['schema'] != 1:
        raise ValueError('Unsupported metrics schema')
    for key in ('system_cycles', 'checked_results'):
        if type(data.get(key)) is not int or data[key] <= 0:
            raise ValueError('Invalid ' + key)
    for key in ('workload', 'memory_model'):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError('Missing ' + key)
    for key in ('external_reads', 'external_writes', 'external_read_bytes',
                'external_write_bytes', 'completed_transactions',
                'request_stall_cycles', 'response_latency_cycles'):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError('Invalid ' + key)
    if (data['external_read_bytes'] != 4 * data['external_reads'] or
            data['external_write_bytes'] > 4 * data['external_writes'] or
            data['completed_transactions'] != data['external_reads'] + data['external_writes'] or
            data['request_stall_cycles'] > data['system_cycles'] + 1 or
            data['response_latency_cycles'] < data['completed_transactions']):
        raise ValueError('Inconsistent traffic counters')
    return data


def compare(baseline, candidate, baseline_mhz=None, candidate_mhz=None):
    for key in ('workload', 'memory_model', 'checked_results'):
        if baseline[key] != candidate[key]:
            raise ValueError('Incomparable ' + key)
    result = {
        'simulation_only': True,
        'hardware_qualified': False,
        'baseline_system_cycles': baseline['system_cycles'],
        'candidate_system_cycles': candidate['system_cycles'],
        'same_clock_speedup': baseline['system_cycles'] / candidate['system_cycles'],
        'limitations': 'Includes boot, memory selftest, GEMM and checking. Not CPU IPC, '
                      'isolated GEMM throughput, physical DDR bandwidth or JAX end-to-end time. '
                      'Caller must verify identical firmware and model sources. The memory '
                      'model is cycle-indexed, so per-request delays can differ between runs.',
    }
    if (baseline_mhz is None) != (candidate_mhz is None):
        raise ValueError('Supply both hypothetical clock frequencies or neither')
    if baseline_mhz is not None:
        if any(not math.isfinite(x) or x <= 0 for x in (baseline_mhz, candidate_mhz)):
            raise ValueError('Clock frequencies must be finite and positive')
        result['hypothetical_baseline_ms'] = baseline['system_cycles'] / (baseline_mhz * 1000)
        result['hypothetical_candidate_ms'] = candidate['system_cycles'] / (candidate_mhz * 1000)
        result['hypothetical_speedup'] = result['same_clock_speedup'] * candidate_mhz / baseline_mhz
        result['clock_caveat'] = ('Assumed system clocks only; cycle scaling does not model changed '
                                 'DDR ratios or absolute memory latency and is not timing acceptance.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--baseline-assumed-mhz', type=float)
    parser.add_argument('--candidate-assumed-mhz', type=float)
    args = parser.parse_args()
    try:
        result = compare(read_metrics(args.baseline.read_text()),
                         read_metrics(args.candidate.read_text()),
                         args.baseline_assumed_mhz, args.candidate_assumed_mhz)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
