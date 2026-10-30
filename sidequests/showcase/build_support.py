"""Shared firmware-only build metadata; no retained route or bitstream is implied."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_logged(command, out, name):
    command = list(map(str, command))
    (out / (name + '-command.json')).write_text(json.dumps(command, indent=2) + '\n')
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError((out / (name + '.log')).read_text()[-6000:])


def memory_report(elf):
    """Check the same 4 KiB stack reservation as bringup.ld and record the margin."""
    lines = subprocess.check_output(['riscv64-unknown-elf-nm', str(elf)], text=True)
    symbols = {parts[2]: int(parts[0], 16) for line in lines.splitlines()
               if len(parts := line.split()) == 3}
    end, top = symbols['__bss_end'], symbols['_stack_top']
    available = top - end
    reserved = symbols.get('_stack_size', 4096)
    if available < reserved:
        raise ValueError(f'Firmware leaves only {available} bytes for the {reserved}-byte stack reservation')
    return {'ram_bytes': top - 0x80000000, 'static_end': end, 'static_bytes': end - 0x80000000,
            'stack_reserved_bytes': reserved, 'remaining_after_stack_bytes': available - reserved,
            'scope': 'Static linker allocation; runtime peak stack is not measured'}


def compile_firmware(source, includes, out, optimization='O2', tpu_transport='mailbox', io_transport='uart', clock_hz=100000000, linker_script=None, extra_objects=(), libraries=()):
    """Compile RV32IM firmware independently of LiteX, FPGA tools, and prior routes."""
    if optimization not in ('Os', 'O2', 'O3'):
        raise ValueError('optimization must be Os, O2 or O3')
    if tpu_transport not in ('mailbox', 'direct'):
        raise ValueError('tpu_transport must be mailbox or direct')
    if io_transport not in ('uart', 'udp'):
        raise ValueError('io_transport must be uart or udp')
    startup = ROOT / 'hardware/synapse32/start.S'
    linker = Path(linker_script) if linker_script else ROOT / 'hardware/synapse32/bringup.ld'
    dependencies = [source, startup, linker, ROOT / 'src/axis_mailbox.c',
                    ROOT / 'src/mmio_backend.c', ROOT / 'include/tiny3tpu_uart_coords.h', ROOT / 'include/tiny3tpu_program_math.h']
    command = ['riscv64-unknown-elf-gcc', '-march=rv32im_zicsr_zifencei', '-mabi=ilp32',
               '-' + optimization, '-ffp-contract=off', '-ffreestanding', '-fno-builtin',
               '-ffunction-sections', '-fdata-sections', '-nostdlib', '-msmall-data-limit=0',
               '-Wall', '-Wextra', '-Werror', f'-DCONFIG_CLOCK_FREQUENCY={int(clock_hz)}UL',
               '-DTINY3TPU_DIRECT_TPU=' + str(int(tpu_transport == 'direct')),
               '-DTINY3TPU_ETHERNET=' + str(int(io_transport == 'udp')),
               '-I' + str(ROOT / 'include'), *['-I' + str(path) for path in includes],
               '-Wl,--no-relax,--gc-sections', '-T' + str(linker), startup, source,
               ROOT / 'src/axis_mailbox.c', ROOT / 'src/mmio_backend.c', *extra_objects, *libraries, '-lgcc',
               '-o', out / 'firmware.elf']
    run_logged(command, out, 'firmware')
    run_logged(['riscv64-unknown-elf-size', out / 'firmware.elf'], out, 'size')
    run_logged(['riscv64-unknown-elf-objcopy', '-O', 'verilog', '--verilog-data-width=4',
                '--change-addresses=-0x80000000', out / 'firmware.elf', out / 'firmware.hex'], out, 'image')
    run_logged(['riscv64-unknown-elf-objcopy', '-O', 'binary', out / 'firmware.elf',
                out / 'firmware.bin'], out, 'binary')
    dependencies += sorted((ROOT / 'include').glob('tiny3tpu_*transport.h'))
    dependencies += list(extra_objects)
    return {'optimization': optimization, 'cpu': 'vexriscv-lite-rv32im', 'clock_hz': int(clock_hz), 'tpu_transport': tpu_transport,
            'io_transport': io_transport,
            'memory': memory_report(out / 'firmware.elf'),
            'gcc_version': subprocess.check_output(['riscv64-unknown-elf-gcc', '--version'], text=True).splitlines()[0],
            'firmware_sha256': {name: sha256(out / name) for name in ('firmware.elf', 'firmware.hex', 'firmware.bin')},
            'source_sha256': {str(path.relative_to(ROOT)): sha256(path) for path in dependencies},
            'implementation': 'Firmware only; no bitstream generated or physical timing validated'}


def native_reference(artifact, options, data):
    """Execute generated C; only the software exponential differs from the CORDIC target."""
    sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
    from test_stablehlo_compiler import Compiled
    compiled = Compiled(artifact, replace(options, target=replace(options.target, cordic_exp=False), symbol='t3p'))
    try:
        status, outputs = compiled.run(data)
        if status:
            raise ValueError(f'Native generated program returned {status}')
        return outputs, int(compiled.library.backend_calls()), compiled.report
    finally:
        compiled.close()


def tpu_placement(report):
    return [entry for entry in report['placement'] if entry.get('device') == 'tpu']


def load_expected_modes(board, legacy):
    """Read new build counts, retaining explicit compatibility with pre-policy images."""
    board = Path(board)
    manifest_path = board / 'build-manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for name, digest in {**manifest.get('firmware_sha256', {}), **manifest.get('reference_sha256', {})}.items():
            path = board / name
            if not path.exists() or sha256(path) != digest:
                raise ValueError(f'Firmware does not match build-manifest.json: {path}')
        records = manifest['modes']
        counts = {int(record['mode']): int(record['expected_backend_calls']) for record in records}
        if set(counts) != set(legacy) or any(value < 0 for value in counts.values()):
            raise ValueError('Incomplete or invalid per-mode backend counts in build-manifest.json')
        return counts, manifest
    # Historical images had fixed TPU counts. Do not guess for newly generated headers.
    for report_path in board.glob('*report.json'):
        report = json.loads(report_path.read_text())
        if 'gemm_policy' in report:
            raise ValueError('Policy-aware firmware requires build-manifest.json; rebuild the firmware')
    return dict(legacy), {'legacy_fixed_tpu_counts': True}
