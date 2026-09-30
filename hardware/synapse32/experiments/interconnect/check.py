#!/usr/bin/env python3
"""Extract unchanged transaction logic, prove equivalence, compare xc7 mapping.

Generated files and logs live only in a caller-supplied /tmp directory.
RAM is abstracted at its read-data boundary; byte-write effects are exposed.
CPU/sequencer/peripherals are cut to arbitrary inputs, without assumptions.
No route, firmware generation, or edits to production RTL are performed.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def controller(source, name):
    start = source.index('    // 1 GiB DRAM')
    body = source[start:source.index('\nendmodule', start)]
    ram_start = body.index('    reg [31:0] boot_mem')
    ram_end = body.index('    wire [$clog2(BOOT_WORDS)', ram_start)
    body = body[:ram_start] + body[ram_end:]
    body = body.replace('    wire [31:0] tpu_data, uart_data;\n', '')
    peripheral_start = body.index('    synapse32_tpu_peripheral accelerator')
    peripheral_end = body.index('    integer lane;', peripheral_start)
    body = body[:peripheral_start] + body[peripheral_end:]
    body = body.replace('boot_mem[boot_index]', 'boot_word')
    write_start = body.index('            for (lane=0;')
    write_end = body.index('\n        end', write_start)
    body = body[:write_start] + body[write_end:]
    # Observe every RAM side effect and address independently of RAM contents.
    body += '''
    assign boot_read = accept && boot_address && !req_write;
    assign boot_write = {4{accept && boot_address && req_write}} & req_wstrb;
    assign boot_addr = boot_index;
    assign boot_wdata = req_wdata;
    assign tpu_read = accept && tpu_address && !req_write;
    assign tpu_write = accept && tpu_address && req_write;
    assign uart_read = accept && uart_address && !req_write;
    assign uart_write = accept && uart_address && req_write && req_wstrb == 15;
'''
    return '''module %s #(parameter BOOT_WORDS=16384)(
    input clk, rst, req_valid, req_write, resp_ready,
    input [31:0] req_addr, req_wdata, tpu_data, uart_data, boot_word,
    input [3:0] req_wstrb,
    output req_ready, resp_valid, resp_error,
    output [31:0] resp_rdata,
    output ext_req_valid, input ext_req_ready,
    output ext_req_write, output [31:0] ext_req_addr, ext_req_wdata,
    output [3:0] ext_req_wstrb,
    input ext_resp_valid, output ext_resp_ready,
    input [31:0] ext_resp_rdata, input ext_resp_error,
    output reg report_valid, exit_valid,
    output reg [31:0] report_data, exit_code,
    output boot_read, output [3:0] boot_write,
    output [$clog2(BOOT_WORDS)-1:0] boot_addr,
    output [31:0] boot_wdata,
    output tpu_read, tpu_write, uart_read, uart_write
);
''' % name + body + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--yosys', default='yosys')
    args = parser.parse_args()
    out = args.out.resolve()
    assert str(out).startswith(('/tmp/', '/private/tmp/')), out
    out.mkdir(parents=True, exist_ok=True)
    sources = {'gold': ROOT / 'hardware/synapse32/synapse32_dram_soc.sv',
               'gate': HERE / 'synapse32_dram_soc.sv'}
    hashes = {}
    for name, path in sources.items():
        source = path.read_text()
        hashes[name] = hashlib.sha256(source.encode()).hexdigest()
        (out / (name + '.sv')).write_text(controller(source, name))
    env = dict(os.environ, OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')

    def run(name, script):
        (out / (name + '.ys')).write_text(script + '\n')
        with (out / (name + '.log')).open('w') as log:
            subprocess.run([args.yosys, '-Q', '-T', '-s', name + '.ys'],
                           cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True)

    # No protocol assumptions: inductive proof includes idle/invalid outputs,
    # arbitrary response timing, backpressure, resets, and all byte strobes.
    proof_sizes = (16384, 3, 32768, 1, 2, 536870912, 536870913, 1073741824)
    for words in proof_sizes:
        run('equiv_' + str(words), '''read_verilog -sv gold.sv gate.sv
chparam -set BOOT_WORDS %d gold gate
proc
opt
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
equiv_induct -seq 4
equiv_status -assert''' % words)
    stats = {}
    for name in sources:
        run('synth_' + name, '''read_verilog -sv %s.sv
synth_xilinx -family xc7 -top %s -noiopad -noclkbuf -json %s.json
check -assert
stat''' % (name, name, name))
        data = json.loads((out / (name + '.json')).read_text())
        stats[name] = dict(Counter(c['type'] for c in data['modules'][name]['cells'].values()))
    result = dict(source_sha256=hashes, cells=stats,
                  proof='equiv_status -assert passed', proof_boot_words=proof_sizes)
    (out / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
