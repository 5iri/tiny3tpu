#!/usr/bin/env python3
"""Check every pixel/TPU coordinate over a complete rotation and bound render time."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from test import ROOT, REPO, SCENE_ASSETS, reference, run
from reference import rasterize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/rotation')
    parser.add_argument('--cpu-firmware',type=Path,help='Check the larger CPU mesh using all 256 JAX outputs')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'src/kc705_hdmi_renderer.sv',ROOT/'src/kc705_hdmi_ram.sv',
             REPO/'multi-core/tpu_core_wrapper.sv',REPO/'systolic_array/rtl/NxN_systolic_array.v',
             REPO/'systolic_array/rtl/pe.v',Path(__file__).with_name('tb_rotation.sv')]
    inputs=[ROOT/'assets/mesh_config.vh',*sources,Path(__file__),ROOT/'tools/reference.py',SCENE_ASSETS/'tools/assets.py',
            *(SCENE_ASSETS/'assets'/name for name in ('mesh.json','vertices.hex','rotations.hex','faces.hex'))]
    coordinates=156672
    if args.cpu_firmware:
        import numpy as np
        firmware=args.cpu_firmware.resolve()
        manifest=json.loads((firmware/'build-manifest.json').read_text())
        for name,sha in manifest['workload_sha256'].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==sha,name
        jax_coordinates=np.load(firmware/'jax-coordinates.npy')
        coordinates=int(jax_coordinates.size)
        inputs += [ROOT/'tools/mesh_assets.py',ROOT/'assets/mesh.json',ROOT/'assets/faces.hex',
                   firmware/'build-manifest.json',firmware/'jax-coordinates.npy']
    hashes={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    with (out/'expected-results.hex').open('w') as qfile,(out/'expected-pixels.hex').open('w') as pfile:
        for phase in range(256):
            if args.cpu_firmware:
                q=jax_coordinates[phase].tolist();pixels=rasterize(q,cpu=True)
            else:q,pixels=reference(phase)
            qfile.write(''.join(f'{v&0xffffffff:08x}\n' for row in q for v in row))
            pfile.write(''.join(f'{v:x}\n' for v in pixels))
    run(['verilator','-I'+str(ROOT/'assets'),'--binary','--timing','--top-module','tb_rotation',
         *(['-GCPU_DRIVEN=1'] if args.cpu_firmware else []),
         str(SCENE_ASSETS/'verilator.vlt'),'-Wno-TIMESCALEMOD','--Mdir',str(out/'obj'),
         '-o',str(out/'simulate-rotation'),'-j','4',*(str(p) for p in sources)],out/'compile.log',SCENE_ASSETS)
    log=run([str(out/'simulate-rotation'),'+OUT_DIR='+str(out)],out/'simulation.log',SCENE_ASSETS)
    assert f'ROTATION_PASS phases=256 coordinates={coordinates} pixels=78643200' in log
    rows=[(int(p),int(c)) for p,c in re.findall(r'ROTATION phase=(\d+) cycles=(\d+)',log)]
    assert [p for p,c in rows]==list(range(256))
    assert max(c for p,c in rows)<(840000 if args.cpu_firmware else 420000)
    for name,expected in hashes.items():
        assert hashlib.sha256((REPO/name).read_bytes()).hexdigest()==expected,name
    worst=max(rows,key=lambda row:row[1]);best=min(c for p,c in rows)
    report=dict(passed=True,scope='Cycle-accurate renderer simulation; CPU mode uploads JAX-generated coordinates, standalone mode executes TPU RTL; nominal 25.2 MHz, no physical latency measurement',
                cpu_driven=bool(args.cpu_firmware),phases=256,coordinates_checked=coordinates,
                vertices=manifest['vertices'] if args.cpu_firmware else 204,triangles=manifest['triangles'] if args.cpu_firmware else 407,
                pixels_checked=78643200,render_resolution=[640,480],raster_lanes=2,
                minimum_cycles=best,maximum_cycles=worst[1],worst_phase=worst[0],
                maximum_render_ms=worst[1]/25200,frame_budget_cycles=840000 if args.cpu_firmware else 420000,
                all_phases_within_target_budget=True,animation_hz=30 if args.cpu_firmware else 60,phase_cycles=dict(rows),sha256=hashes)
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('sha256','phase_cycles')},indent=2))


if __name__=='__main__':main()
