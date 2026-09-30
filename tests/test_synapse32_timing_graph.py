"""Graph algorithm tests independent of FPGA RTL implementation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('graph',Path(__file__).resolve().parents[1]/'tools/synapse32_analyze_timing_graph.py')
graph=importlib.util.module_from_spec(spec);spec.loader.exec_module(graph)

class TimingGraphTest(unittest.TestCase):
    def run_graph(self, lines, tracked_cells=()):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'graph.tsv';p.write_text('VERSION\t1\n'+'\n'.join(lines)+'\n')
            return graph.analyze(p,tracked_cells=tracked_cells)

    def mixed(self, source_delay, output_delay):
        return self.run_graph([
            'PORT\tsrc\tFF\tCK\tinput\t0\t0\tsource_clock',
            'PORT\tsrc\tFF\tQ\toutput\t3\t1\tdata',
            f'CLOCK\tsrc\tQ\t0\tCK\t0\t0\t0\t{source_delay}',
            'PORT\tmix\tDSP\tCK\tinput\t0\t0\tinternal_clock',
            'PORT\tmix\tDSP\tC\tinput\t4\t0\tdata',
            'PORT\tmix\tDSP\tP\toutput\t5\t1\tresult',
            f'CLOCK\tmix\tP\t0\tCK\t0\t0\t0\t{output_delay}',
            'CELLARC\tmix\tC\tP\t2.0',
            'NETARC\tdata\tsrc\tQ\tmix\tC\t1.0',
            'NETARC\tresult\tmix\tP\tdst\tD\t1.5',
            'PORT\tdst\tFF\tCK\tinput\t0\t0\tinternal_clock',
            'PORT\tdst\tFF\tD\tinput\t2\t1\tresult',
            'CLOCK\tdst\tD\t0\tCK\t0\t0.5\t0\t0',
        ])

    def test_mixed_output_keeps_both_origins(self):
        for source, output in [(1,2),(1,9),(8,2)]:
            result=self.mixed(source,output)
            self.assertFalse(result['unresolved_nodes'])
            arrivals={r['source_clock']:r['arrival_ns'] for r in result['maxima']}
            self.assertEqual(arrivals,{'source_clock':source+5,'internal_clock':output+2})

    def test_tracked_origin_survives_same_clock_merge(self):
        # A slow unrelated source must not erase the separately tracked RAM
        # path when both launch from the same clock into a shared merge.
        r=self.run_graph([
            'PORT\tram\tRAM\tCK\tinput\t0\t0\tclk',
            'PORT\tram\tRAM\tQ\toutput\t3\t1\tfast',
            'CLOCK\tram\tQ\t0\tCK\t0\t0\t0\t1',
            'PORT\tslow\tFF\tCK\tinput\t0\t0\tclk',
            'PORT\tslow\tFF\tQ\toutput\t3\t1\tslow',
            'CLOCK\tslow\tQ\t0\tCK\t0\t0\t0\t10',
            'PORT\tm\tLUT\tA\tinput\t4\t0\tfast',
            'PORT\tm\tLUT\tB\tinput\t4\t0\tslow',
            'PORT\tm\tLUT\tO\toutput\t5\t0\tresult',
            'NETARC\tfast\tram\tQ\tm\tA\t1',
            'NETARC\tslow\tslow\tQ\tm\tB\t1',
            'CELLARC\tm\tA\tO\t2',
            'CELLARC\tm\tB\tO\t2',
            'PORT\tdst\tFF\tCK\tinput\t0\t0\tclk',
            'PORT\tdst\tFF\tD\tinput\t2\t1\tresult',
            'CLOCK\tdst\tD\t0\tCK\t0\t0.5\t0\t0',
            'NETARC\tresult\tm\tO\tdst\tD\t1',
        ],tracked_cells=['ram'])
        self.assertEqual(r['maxima'][0]['arrival_ns'],14.5)
        self.assertEqual(r['tracked_maxima'][0]['arrival_ns'],5.5)
        self.assertEqual(r['tracked_maxima'][0]['path'][0]['cell'],'ram')

    def test_combinational_loop_remains_explicit(self):
        r=self.run_graph(['PORT\tx\tLUT\tI\tinput\t4\t0\tn',
                          'PORT\tx\tLUT\tO\toutput\t5\t0\tn',
                          'CELLARC\tx\tI\tO\t1',
                          'NETARC\tn\tx\tO\tx\tI\t1'])
        self.assertEqual(len(r['unresolved_nodes']),2)

    def test_recovers_picoseconds_from_float_export(self):
        self.assertEqual(graph.ps('0.731000020'),731)
        self.assertEqual(graph.ps('0.099999994'),100)

if __name__=='__main__':unittest.main()
