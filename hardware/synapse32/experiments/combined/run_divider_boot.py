#!/usr/bin/env python3
"""One builder-based divider+bootdecode experiment, with original CSR.

Also serves as the builder's --yosys hook, modifying only the isolated script.
All generated files live in a unique /tmp directory. Never invoke builder route.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CPU = ROOT.parent / 'synapse32'
DIV = HERE.parent / 'divider'
BASE = ROOT / 'build-ddr-divider'
YOSYS = Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
NEXTPNR = Path('/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx')
CHIPDB = NEXTPNR.parent.parent / 'kc705.bin'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def yosys_hook():
    script_path = Path(sys.argv[sys.argv.index('-s') + 1]).resolve()
    build = script_path.parent
    assert build.parent.name.startswith('tiny3tpu-divider-boot-')
    for name in ('firmware.hex', 'kc705.xdc'):
        assert digest(build / name) == digest(BASE / name), name
    ddr = Path('litedram/gateware/kc705_dram.v')
    def strip_comments(text):
        return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    assert strip_comments((build / ddr).read_text()) == strip_comments((BASE / ddr).read_text())
    # Generator timestamps/hierarchy comments vary. Pin byte-identical parent RTL.
    (build / ddr).write_bytes((BASE / ddr).read_bytes())
    script = script_path.read_text()
    expected = (BASE / 'synth.ys').read_text().replace(str(BASE), str(build))
    assert script == expected, 'builder source list/options drifted from divider baseline'
    assert str(CPU / 'rtl/core_modules/csr_exec.v') in script
    (build / 'divider-only.ys').write_text(script)
    original = ROOT / 'hardware/synapse32/synapse32_dram_soc.sv'
    candidate = build.parent / 'synapse32_dram_soc.sv'
    assert script.count(str(original)) == 1
    script_path.write_text(script.replace(str(original), str(candidate)))
    print('PASS: baseline builder script, firmware/XDC/DDR RTL; only bootdecode substituted', flush=True)
    os.execv(str(YOSYS), [str(YOSYS), *sys.argv[1:]])


def main():
    resume = len(sys.argv) == 3 and sys.argv[1] == '--resume'
    out = Path(sys.argv[2]) if resume else Path(tempfile.mkdtemp(prefix='tiny3tpu-divider-boot-', dir='/tmp'))
    assert out.is_absolute() and out.name.startswith('tiny3tpu-divider-boot-')
    build = out / 'build'
    print(out, flush=True)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('NEXTPNR_') and k != 'CSR_OVERLAY'}
    env.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
               VECLIB_MAXIMUM_THREADS='2', PYTHONDONTWRITEBYTECODE='1')
    manifest = {'out': str(out), 'build': str(build), 'commands': [],
                'route_count': 0, 'synthesis_jobs_max': 1, 'compile_jobs_max': 2,
                'diagnostic_only': True, 'csr_overlay': False,
                'environment': {k: env[k] for k in ('OMP_NUM_THREADS',
                    'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}}
    sources = {Path(p) for p in re.findall(r'(?<=\s)/[^\s\"]+\.(?:vh|sv|v)(?=\s|$)',
                                          (BASE / 'synth.ys').read_text())}
    sources |= set((CPU / 'rtl').rglob('*.v')) | set((CPU / 'rtl').rglob('*.vh'))
    sources |= set(DIV.glob('*.v')) | {DIV / 'divider_tb.sv', DIV / 'cpu_tb.sv'}
    sources |= {ROOT / 'tools/kc705_open_build.py', ROOT / 'CMakeLists.txt',
        HERE.parent / 'interconnect/synapse32_dram_soc.sv',
        HERE.parent / 'interconnect/check.py', HERE.parent / 'interconnect/compare_full.py',
        DIV / 'BOARD_RESULTS.md', DIV / 'SOURCE_SHA256.txt',
        BASE / 'soc.json', BASE / 'synth.ys', BASE / 'firmware.hex', BASE / 'kc705.xdc',
        BASE / 'route.log', YOSYS, NEXTPNR, CHIPDB}
    manifest['input_sha256'] = {str(p): digest(p) for p in sorted(sources)}
    if resume:
        previous = json.loads((out / 'manifest.json').read_text())
        assert previous['route_count'] == 0, 'Never resume/repeat a route'
        # Test-harness development may proceed independently of frozen evidence.
        # Keep the already executed harness and its original hash, not a new test claim.
        verify_hash = previous['input_sha256'].pop(str(DIV / 'verify.sh'), None)
        if verify_hash:
            previous['executed_verify_source_sha256'] = verify_hash
            previous['verify_changed_externally'] = digest(DIV / 'verify.sh') != verify_hash
        assert previous['input_sha256'] == manifest['input_sha256'], 'Inputs changed'
        manifest = previous
    assert digest(CHIPDB) == 'd3d90cb680525dcf42b19dde35df9660ca7a9a48b5865bd33404129a2595b284'
    assert digest(NEXTPNR) == '8b80c5f49fbb8d9433305d904ef707bd0f2cf4b18afb77f41fe9f5d511687cc9'
    assert digest(BASE / 'kc705.xdc') == 'e1c892563932bfae60eddf7253e123a06239bce6c2c1ac3928186ba00921f10c'
    (out / 'synapse32_dram_soc.sv').write_bytes(
        (HERE.parent / 'interconnect/synapse32_dram_soc.sv').read_bytes())
    manifest['boot_overlay_sha256'] = digest(out / 'synapse32_dram_soc.sv')

    def save():
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    def run(name, args):
        if any(c['name'] == name and c.get('returncode') == 0 for c in manifest['commands']):
            print(name + ' already passed; retained', flush=True)
            return
        attempts = sum(c['name'] == name for c in manifest['commands'])
        command = {'name': name, 'argv': list(map(str, args))}
        logfile = out / (name + (f'.retry{attempts}' if attempts else '') + '.log')
        command['log'] = str(logfile)
        manifest['commands'].append(command)
        save()
        print(name, flush=True)
        with logfile.open('w') as log:
            result = subprocess.run(command['argv'], cwd=ROOT, env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
        command['returncode'] = result.returncode
        save()
        if result.returncode:
            raise RuntimeError(f'{name} failed: {out / (name + ".log")}')

    run('boot-equivalence', ['python3', HERE.parent / 'interconnect/check.py',
        '--out', out / 'proof', '--yosys', '/opt/homebrew/bin/yosys'])
    proof = json.loads((out / 'proof/results.json').read_text())
    assert proof['source_sha256']['gate'] == manifest['boot_overlay_sha256']
    manifest['boot_equivalence'] = proof
    # Relocate only the existing test harness's path assignments; keep all tests.
    verify = (DIV / 'verify.sh').read_text()
    lines = verify.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('HERE='):
            lines[i] = f'HERE="{DIV}"'
        elif line.startswith('BUILD='):
            lines[i] = f'BUILD="{out / "divider-tests"}"\nmkdir -p "$BUILD"'
    if not (out / 'verify-divider.sh').exists():
        (out / 'verify-divider.sh').write_text('\n'.join(lines) + '\n')
    run('divider-tests', ['bash', out / 'verify-divider.sh'])
    run('builder', [ROOT / '.venv-ddr-compat/bin/python', ROOT / 'tools/kc705_open_build.py',
        'synth', '--synapse32-dir', CPU, '--cpu-overlay-dir', DIV,
        '--build-dir', build, '--yosys', Path(__file__).resolve()])
    run('preservation', ['python3', HERE.parent / 'interconnect/compare_full.py',
        BASE / 'soc.json', build / 'soc.json'])
    gold, gate = [json.loads(p.read_text())['modules']['kc705_synapse32_top']
                  for p in (BASE / 'soc.json', build / 'soc.json')]
    kinds = {c['type'] for c in gold['cells'].values()} - {
        '$scopeinfo', 'CARRY4', 'INV', 'MUXF7', 'MUXF8',
        'LUT1', 'LUT2', 'LUT3', 'LUT4', 'LUT5', 'LUT6'}
    for kind in kinds:
        params = [Counter(json.dumps(c['parameters'], sort_keys=True)
                          for c in m['cells'].values() if c['type'] == kind)
                  for m in (gold, gate)]
        assert params[0] == params[1], kind
    for kind in ('RAM32M', 'RAMB36E1'):
        params = [{n: c['parameters'] for n, c in m['cells'].items() if c['type'] == kind}
                  for m in (gold, gate)]
        assert params[0] == params[1], kind
    manifest['preserved_parameter_kinds'] = sorted(kinds)
    manifest['named_ram_parameters_init_match'] = True
    manifest['cells'] = {name: dict(Counter(c['type'] for c in m['cells'].values()))
                         for name, m in [('divider', gold), ('divider_boot', gate)]}
    assert manifest['input_sha256'] == {str(p): digest(p) for p in sorted(sources)}
    manifest['route_count'] = 1
    save()
    run('route', [NEXTPNR, '--chipdb', CHIPDB, '--xdc', build / 'kc705.xdc',
        '--freq', '100', '--seed', '4', '--json', build / 'soc.json',
        '--write', build / 'soc_routed.json', '--report', build / 'timing.json',
        '--log', build / 'route.log'])
    manifest['final_fmax'] = json.loads((build / 'timing.json').read_text())['fmax']
    manifest['inputs_unchanged'] = manifest['input_sha256'] == {
        str(p): digest(p) for p in sorted(sources)}
    manifest['overlay_unchanged'] = digest(out / 'synapse32_dram_soc.sv') == manifest['boot_overlay_sha256']
    manifest['output_sha256'] = {str(p.relative_to(out)): digest(p) for p in [
        build / n for n in ('synth.ys', 'divider-only.ys', 'soc.json', 'soc_routed.json',
                            'firmware.hex', 'kc705.xdc', 'timing.json', 'route.log')]
        + [out / 'divider-tests.log', out / 'preservation.log']}
    save()
    assert manifest['inputs_unchanged'] and manifest['overlay_unchanged']
    print(json.dumps(manifest['final_fmax'], indent=2), flush=True)


if __name__ == '__main__':
    if '-s' in sys.argv:
        yosys_hook()
    else:
        main()
