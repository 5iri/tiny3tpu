"""Shared firmware-only build metadata; no retained route or bitstream is implied."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[3]


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


def compile_firmware(source, includes, out, optimization='O2', tpu_transport='mailbox', clock_hz=100000000, linker_script=None):
    """Compile RV32IM firmware independently of LiteX, FPGA tools, and prior routes."""
    if optimization not in ('Os', 'O2', 'O3'):
        raise ValueError('optimization must be Os, O2 or O3')
    if tpu_transport not in ('mailbox', 'direct'):
        raise ValueError('tpu_transport must be mailbox or direct')
    startup = ROOT / 'hardware/synapse32/start.S'
    linker = Path(linker_script) if linker_script else ROOT / 'hardware/synapse32/bringup.ld'
    dependencies = [source, startup, linker, ROOT / 'src/axis_mailbox.c',
                    ROOT / 'src/mmio_backend.c', ROOT / 'include/tiny3tpu_program_math.h']
    command = ['riscv64-unknown-elf-gcc', '-march=rv32im_zicsr_zifencei', '-mabi=ilp32',
               '-' + optimization, '-ffp-contract=off', '-ffreestanding', '-fno-builtin',
               '-ffunction-sections', '-fdata-sections', '-nostdlib', '-msmall-data-limit=0',
               '-Wall', '-Wextra', '-Werror', f'-DCONFIG_CLOCK_FREQUENCY={int(clock_hz)}UL',
               '-DTINY3TPU_DIRECT_TPU=' + str(int(tpu_transport == 'direct')),
               '-I' + str(ROOT / 'include'), *['-I' + str(path) for path in includes],
               '-Wl,--no-relax,--gc-sections', '-T' + str(linker), startup, source,
               ROOT / 'src/axis_mailbox.c', ROOT / 'src/mmio_backend.c', '-lgcc',
               '-o', out / 'firmware.elf']
    run_logged(command, out, 'firmware')
    run_logged(['riscv64-unknown-elf-size', out / 'firmware.elf'], out, 'size')
    run_logged(['riscv64-unknown-elf-objcopy', '-O', 'verilog', '--verilog-data-width=4',
                '--change-addresses=-0x80000000', out / 'firmware.elf', out / 'firmware.hex'], out, 'image')
    run_logged(['riscv64-unknown-elf-objcopy', '-O', 'binary', out / 'firmware.elf',
                out / 'firmware.bin'], out, 'binary')
    return {'optimization': optimization, 'cpu': 'vexriscv-lite-rv32im', 'clock_hz': int(clock_hz), 'tpu_transport': tpu_transport,
            'memory': memory_report(out / 'firmware.elf'),
            'gcc_version': subprocess.check_output(['riscv64-unknown-elf-gcc', '--version'], text=True).splitlines()[0],
            'firmware_sha256': {name: sha256(out / name) for name in ('firmware.elf', 'firmware.hex', 'firmware.bin')},
            'source_sha256': {str(path.relative_to(ROOT)): sha256(path) for path in dependencies},
            'implementation': 'Firmware only; no bitstream generated or physical timing validated'}

