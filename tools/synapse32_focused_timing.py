#!/usr/bin/env python3
"""Inspect named timing cones using existing expanded diagnostic graphs.

Reports model intervals, not physical timing closure. Useful for distinguishing
a removed path from another path made worse by changed placement.
"""
import argparse
import hashlib
import json
from pathlib import Path
from synapse32_analyze_timing_graph import analyze


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sensitivity', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args(); folder = a.sensitivity.resolve(); out = a.out.resolve()
    manifest_path = folder/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for n, h in manifest['sha256'].items():
        assert digest(n) == h, n
    graph = folder/'graph-pcout-0-carry-0.1.tsv'
    variant = next(v for v in manifest['variants'] if v['symbolic_carry_arc_ns'] == .1)
    assert digest(graph) == variant['graph_sha256']
    groups = {name: set() for name in ['boot_ram_inputs','dma_last_inputs','ddr_id_fifo_inputs',
                                      'ddr_first_outputs','ddr_write_queue_inputs','ddr_buffer_outputs',
                                      'dma_address_inputs','dma_remaining_inputs']}
    ports = {}
    for line in graph.open():
        v = line.rstrip('\n').split('\t')
        if v[0] != 'PORT':
            continue
        _, c, t, port, direction, cls, n, net = v
        ports[c, port] = net
        if c.startswith('soc.boot_mem.') and t.startswith('RAMB36E1'):
            groups['boot_ram_inputs'].add(c)
        if port == 'Q':
            if net.startswith('soc.dma.engine.axi_dma_wr_inst.output_last_cycle_reg'):
                groups['dma_last_inputs'].add(c)
            if net.startswith('soc.dma.engine.axi_dma_wr_inst.addr_reg['):
                groups['dma_address_inputs'].add(c)
            if net.startswith('soc.dma.engine.axi_dma_wr_inst.op_word_count_reg['):
                groups['dma_remaining_inputs'].add(c)
            if net.startswith('memory.main_write_id_buffer_level['):
                groups['ddr_id_fifo_inputs'].add(c)
            if net.startswith('memory.main_write_w_buffer_level2['):
                groups['ddr_write_queue_inputs'].add(c)
            if net.startswith(('memory.main_write_w_buffer_level0[','memory.main_write_w_buffer_readable')):
                groups['ddr_buffer_outputs'].add(c)
            if net.startswith(('memory.main_write_beat_count[','memory.main_write_first_q',
                               'memory.main_write_aw_first')):
                groups['ddr_first_outputs'].add(c)
    results = {}
    for name, cells in groups.items():
        assert cells, name
        result = analyze(graph, tracked_cells=cells)
        assert not result['unresolved_nodes']
        kind = 'tracked_output' if name.endswith('_outputs') else 'tracked_input'
        paths = [v for v in result['tracked_maxima'] if v['group'] == kind]
        assert paths, name
        for path in paths:
            for point in path['path']:
                point['net'] = ports[point['cell'], point['port']]
        results[name] = dict(cells=sorted(cells), maxima=paths,
                             worst_ns=max(v['arrival_ns'] for v in paths))
    out.parent.mkdir(parents=True, exist_ok=True)
    assert not out.exists()
    out.write_text(json.dumps(dict(scope=__doc__, symbolic_pcout_ns=0, symbolic_carry_arc_ns=.1,
        results=results, full_soc_timing_accepted=False,
        sha256={str(q):digest(q) for q in [manifest_path,graph,Path(__file__).resolve(),
                  Path(__file__).with_name('synapse32_analyze_timing_graph.py').resolve()]}), indent=2)+'\n')
    print(json.dumps({k:v['worst_ns'] for k,v in results.items()}))


if __name__ == '__main__':
    main()
