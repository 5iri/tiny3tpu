#!/usr/bin/env python3
"""Compare each fresh banana RTL reply with independently advanced JAX state."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import jax
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequests.showcase.prepare import banana_workload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesh', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--simulation', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    mesh = np.load(args.mesh)
    metadata = json.loads(args.metadata.read_text())
    report = json.loads(args.simulation.read_text())
    if not report.get('passed') or not report.get('banana_only'):
        raise ValueError('Expected a passing --banana-only simulation report')
    count = 1+3*len(mesh['vertices'])
    function = jax.jit(banana_workload(mesh['vertices'], metadata['mesh_scale']))
    angle = np.zeros(1, np.float32)
    checks, angles = [], []
    for row in report['checks']:
        if row['kind'] != 'inference':
            continue
        payload = bytes.fromhex(row['response_hex'])
        if payload[:4] != b'IFR1':
            raise ValueError('Unexpected application reply')
        encoded, checksum = struct.unpack_from('<II', payload, 20)
        if encoded & 0x7fffffff != count:
            raise ValueError('Mesh and response dimensions differ')
        if encoded >> 31:
            if len(payload) != 44+2*(count-1):
                raise ValueError('Invalid compact response length')
            bases = np.frombuffer(payload[32:44], dtype='<i4').astype(np.int64)
            offsets = np.frombuffer(payload[44:], dtype='<u2').reshape(-1, 3).astype(np.int64)
            actual = np.concatenate((np.frombuffer(payload[28:32], dtype='<f4'),
                                     (bases+offsets).ravel().astype(np.float32)))
        else:
            if len(payload) != 28+4*count:
                raise ValueError('Invalid raw response length')
            actual = np.frombuffer(payload[28:], dtype='<f4')
        if int(np.bitwise_xor.reduce(actual.view(np.uint32))) != checksum:
            raise ValueError('Decoded response checksum mismatch')
        expected = np.asarray(function(angle))
        checks.append(dict(step=row['banana_step'],
                           bit_exact=bool(np.array_equal(actual.view(np.uint32), expected.view(np.uint32))),
                           max_abs_error=float(np.max(np.abs(actual-expected))),
                           within_original_tolerance=bool(np.allclose(actual, expected, rtol=5e-6, atol=5e-6))))
        angle = expected[:1].copy()
        angles.append(float(actual[0]))
    if not checks:
        raise ValueError('No fresh frames in simulation report')
    paths = [args.mesh, args.metadata, args.simulation, Path(__file__).resolve(),
             ROOT/'sidequests/showcase/prepare.py']
    result = dict(passed=all(r['within_original_tolerance'] for r in checks),
                  scope='Every fresh RTL reply decoded and compared to independent JAX execution; JAX angle advances from its own preceding output. Original exporter tolerance rtol=atol=5e-6.',
                  frames=len(checks), bit_exact_frames=sum(r['bit_exact'] for r in checks),
                  angle_wraps=int((np.diff(angles) < 0).sum()),
                  max_abs_error=max(r['max_abs_error'] for r in checks),
                  sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, checks=checks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('checks','sha256')}))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
