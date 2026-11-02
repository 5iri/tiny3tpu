#!/usr/bin/env python3
"""Sweep real banana meshes through generated firmware and the production CPU RTL.

All builds are isolated. The production showcase firmware is copied with only its
reply-buffer bound changed to min(4096, max(2480, raw response size)). Larger meshes
therefore use compact responses for this experiment. The existing viewer is not
changed. Link failures retain the real 64 KiB RAM and 4 KiB stack reservation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import jax
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequests.banana.render import reduce_mesh
from sidequests.showcase.prepare import banana_workload
from sidequests.showcase.build_support import compile_firmware, native_reference, sha256
from tools.jax_stablehlo import export_function
from tools.program import CompileOptions, KC705

OBJ_SHA256 = 'f0f8267c7f7cfc64430cb5f8ee6dfa9b1ec7cac6109a39ad96e89f7a57433098'


def load_mesh(path):
    if sha256(path) != OBJ_SHA256:
        raise ValueError('Expected the pinned original jaxsim banana OBJ')
    vertices, faces = [], []
    for line in path.read_text().splitlines():
        row = line.split()
        if not row:
            continue
        if row[0] == 'v':
            vertices.append(list(map(float, row[1:4])))
        elif row[0] == 'f':
            indices = [int(s.split('/')[0])-1 for s in row[1:]]
            faces.extend([indices[0], indices[i], indices[i+1]] for i in range(1, len(indices)-1))
    vertices = np.asarray(vertices, np.float32)
    vertices = (vertices-(vertices.max()+vertices.min())/2)*5
    return vertices, np.asarray(faces, np.int32)


def run(command, directory, name):
    command = list(map(str, command))
    (directory/(name+'-command.json')).write_text(json.dumps(command, indent=2)+'\n')
    with (directory/(name+'.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError((directory/(name+'.log')).read_text()[-6000:])


def grid_value(value):
    parts = [int(s) for s in value.split('x')]
    if len(parts) not in (1, 3) or min(parts) < 2:
        raise argparse.ArgumentTypeError('Use a grid like 12 or 12x13x11, each axis >=2')
    return parts[0] if len(parts) == 1 else np.array(parts)


def prepare_case(args, label, original):
    directory = args.out/('grid-'+label)
    directory.mkdir(parents=True, exist_ok=True)
    vertices, faces = reduce_mesh(*original, grid_value(label), np)
    count = len(vertices)
    scale = 110./float(np.abs(vertices).max())
    quantized = np.rint(vertices*scale).astype(np.int8)
    triangles = quantized[faces].astype(np.int32)
    zero_area = int(np.all(np.cross(triangles[:, 1]-triangles[:, 0],
                                    triangles[:, 2]-triangles[:, 0]) == 0, axis=1).sum())
    raw_bytes, compact_bytes = 32+12*count, 44+6*count
    record = dict(grid=label, vertices=count, triangles=len(faces),
                  quantized_zero_area_triangles=zero_area,
                  raw_response_bytes=raw_bytes, compact_response_bytes=compact_bytes,
                  raw_fits_protocol=raw_bytes <= 4096, compact_fits_protocol=compact_bytes <= 4096,
                  reply_buffer_bytes=min(4096, max(2480, raw_bytes)),
                  optimization=args.optimization, mesh_scale=scale)
    np.savez(directory/'mesh.npz', vertices=vertices, faces=faces)
    (directory/'mesh.json').write_text(json.dumps(record, indent=2)+'\n')
    record['mesh_sha256'] = sha256(directory/'mesh.npz')
    artifacts = directory/'artifacts'
    for name in ('quantized_mlp', 'attention_block'):
        shutil.copytree(args.artifacts/name, artifacts/name, dirs_exist_ok=True)
    banana = artifacts/'banana'
    banana.mkdir(parents=True, exist_ok=True)
    initial = np.zeros(1, np.float32)
    function = banana_workload(vertices, scale)
    artifact = banana/'program.mlirbc'
    export_function(function, initial, output=artifact)
    np.save(banana/'input.npy', initial)
    options = CompileOptions(target=KC705, math_mode='freestanding',
                             allow_approximation=True, gemm_policy='auto')
    outputs, calls, _ = native_reference(artifact, options, initial)
    expected = np.asarray(jax.jit(function)(initial))
    np.testing.assert_allclose(outputs[0], expected, rtol=5e-6, atol=5e-6)
    np.save(banana/'expected-native.npy', outputs[0])
    np.save(banana/'expected-jax.npy', expected)
    record['native_jax_passed'] = True
    record['native_backend_calls'] = calls
    record['artifact_sha256'] = sha256(artifact)
    board = directory/'board'
    run([sys.executable, ROOT/'sidequests/showcase/build_board.py', '--headers-only',
         '--artifacts', artifacts, '--out', board, '--io-transport', 'udp'], directory, 'headers')
    source = (ROOT/'sidequests/showcase/firmware.c').read_text()
    old = '#define TINY3TPU_MAX_RESPONSE_BYTES 2480U'
    if source.count(old) != 1:
        raise ValueError('Production firmware reply declaration changed; review the experiment')
    source = source.replace(old, '#define TINY3TPU_MAX_RESPONSE_BYTES '+str(record['reply_buffer_bytes'])+'U')
    experiment = board/'capacity_firmware.c'
    experiment.write_text(source)
    record['firmware_patch'] = 'Only TINY3TPU_MAX_RESPONSE_BYTES changed; all four application modes retained'
    try:
        manifest = compile_firmware(experiment, [board], board, args.optimization, 'mailbox', 'udp')
    except RuntimeError as error:
        message = str(error)
        if not any(s in message for s in ('insufficient stack space', 'overflowed by', 'will not fit in region')):
            raise
        record.update(build_passed=False, failure='64 KiB RAM / 4 KiB reserved stack limit',
                      failure_detail=message, firmware_source_sha256=sha256(experiment))
        return record
    records = json.loads((board/'modes.json').read_text())
    generated = [board/'fixture.h']
    for mode in records:
        generated.extend([board/(mode['symbol']+'.h'), artifacts/mode['name']/'program.mlirbc',
                          artifacts/mode['name']/'input.npy'])
    manifest.update(schema_version=1, gemm_policy='auto', modes=records,
                    capabilities=['compact-coordinates-v1'],
                    reference_sha256={r['expected_file']:sha256(board/r['expected_file']) for r in records},
                    generated_and_input_sha256={str(p):sha256(p) for p in generated},
                    artifact_dir=str(artifacts), capacity_experiment=record)
    (board/'build-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    record.update(build_passed=True, memory=manifest['memory'], board=str(board),
                  firmware_sha256=manifest['firmware_sha256'],
                  firmware_source_sha256=sha256(experiment))
    return record


def simulate(args, record):
    if not record['build_passed'] or not record['compact_fits_protocol']:
        return
    board = Path(record['board'])
    directory = board.parent
    selected = 'both' if record['raw_fits_protocol'] else 'compact'
    destination = directory/('full-mac' if args.with_mac else 'udp-sim')
    command = [sys.executable, ROOT/'tests/test_udp_soc.py', '--board', board,
               '--out', destination, '--banana-only', '--banana-frames', args.frames,
               '--banana-format', selected]
    if args.with_mac:
        command += ['--with-mac', '--ethernet-python', args.ethernet_python]
    run(command, directory, 'full-mac' if args.with_mac else 'udp-sim')
    report = json.loads((destination/'report.json').read_text())
    rows = [r for r in report['checks'] if r['kind'] == 'inference']
    record['simulation'] = dict(passed=report['passed'], scope=report['scope'],
                               report=str(destination/'report.json'), report_sha256=sha256(destination/'report.json'),
                               requests=report['requests'], fresh_frames=len(rows), formats={})
    for name in ('raw', 'compact'):
        group = [r for r in rows if r['compact'] == (name == 'compact')]
        if not group:
            continue
        latencies = [r['roundtrip_us'] for r in group]
        computes = [r['compute_cycles']/100. for r in group]
        record['simulation']['formats'][name] = dict(
            frames=len(group), roundtrip_us_min=min(latencies), roundtrip_us_max=max(latencies),
            roundtrip_us_mean=float(np.mean(latencies)), compute_us_mean=float(np.mean(computes)),
            simulated_fps_from_mean=1e6/float(np.mean(latencies)),
            datagrams=sorted(set(r['datagrams'] for r in group)),
            verified_words=sorted(set(r['verified_words'] for r in group)),
            checks=[{k:v for k,v in r.items() if k != 'response_hex'} for r in group])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesh-source', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, default=ROOT/'build-showcase')
    parser.add_argument('--out', type=Path, default=ROOT/'build-banana-capacity/sweep')
    parser.add_argument('--grids', nargs='+', default=['6','8','9','10','11','12','13','15'])
    parser.add_argument('--frames', type=int, default=3)
    parser.add_argument('--optimization', choices=('O2','O3','Os'), default='O2')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--with-mac', action='store_true')
    parser.add_argument('--ethernet-python', type=Path, default=ROOT/'.venv-ddr-compat/bin/python')
    args = parser.parse_args()
    if args.frames < 1:
        parser.error('--frames must be positive')
    for name in ('out','mesh_source','artifacts'):
        setattr(args, name, getattr(args, name).resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    original = load_mesh(args.mesh_source)
    report = dict(schema_version=1, scope=__doc__.strip(), source_obj_sha256=sha256(args.mesh_source),
                  source_sha256={str(p.relative_to(ROOT)):sha256(p) for p in [Path(__file__).resolve(),
                       ROOT/'sidequests/showcase/prepare.py',ROOT/'sidequests/showcase/firmware.c',
                       ROOT/'include/tiny3tpu_demo_transport.h',ROOT/'tests/test_udp_soc.py']},
                  physical_validation=False, clock_hz=100000000,
                  wire_protocol_max_bytes=4096, reserved_stack_bytes=4096, ram_bytes=65536,
                  host_viewer_note='Existing viewer still fixes 204 vertices/407 faces; these are isolated firmware and simulation builds.',
                  cases=[])
    for label in args.grids:
        grid_value(label)
        record = prepare_case(args, label, original)
        if not args.build_only:
            simulate(args, record)
        report['cases'].append(record)
        (args.out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({k:v for k,v in record.items() if k not in ('simulation','failure_detail')}), flush=True)
        if 'simulation' in record:
            print(json.dumps(record['simulation']['formats']), flush=True)
    print(args.out/'report.json')


if __name__ == '__main__':
    main()
