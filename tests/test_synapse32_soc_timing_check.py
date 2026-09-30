"""A fast native headline must never mask incomplete SoC timing coverage."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from synapse32_check_soc_timing import REQUIRED_VALIDATIONS, actual_native_graph, budget, decide


class SocTimingCheckTest(unittest.TestCase):
    def decision(self, **changes):
        evidence = dict(missing_carry_arcs=0, ignored_dynamic_ports=0, unknown_delays=False,
                        validation={name: True for name in REQUIRED_VALIDATIONS},
                        intervals=[dict(domain='clk -> clk', delay_ns=9.9, budget_ns=10)],
                        unresolved_nodes=False)
        evidence.update(changes)
        return decide(**evidence)

    def test_complete_synthetic_evidence_passes(self):
        self.assertTrue(self.decision()['accepted'])

    def test_missing_carry_fails_even_when_reported_delay_fits(self):
        self.assertFalse(self.decision(missing_carry_arcs=1)['accepted'])

    def test_unclassified_dynamic_port_fails(self):
        self.assertFalse(self.decision(ignored_dynamic_ports=1)['accepted'])

    def test_symbolic_delay_is_not_device_validation(self):
        self.assertFalse(self.decision(unknown_delays=True)['accepted'])

    def test_absent_validation_does_not_default_to_pass(self):
        self.assertFalse(self.decision(validation={})['accepted'])
        evidence = {name: True for name in REQUIRED_VALIDATIONS}
        evidence.pop('clock_skew_and_hold')
        self.assertFalse(self.decision(validation=evidence)['accepted'])

    def test_slow_or_invalid_path_fails(self):
        for delay, limit in [(10.001, 10), (float('nan'), 10), (float('inf'), 10), (1, None), (1, 0)]:
            with self.subTest(delay=delay, limit=limit):
                self.assertFalse(self.decision(intervals=[dict(domain='test', delay_ns=delay, budget_ns=limit)])['accepted'])

    def test_empty_or_unresolved_graph_fails(self):
        self.assertFalse(self.decision(intervals=[])['accepted'])
        self.assertFalse(self.decision(unresolved_nodes=True)['accepted'])

    def test_related_opposite_edges_get_half_cycle(self):
        row = dict(source_clock='clk', sink_clock='soc.cpu_clk', source_edge=0, sink_edge=1)
        self.assertEqual(budget(row), 5)
        row['sink_clock'] = 'unproven_clock'
        self.assertIsNone(budget(row))

    def test_guided_native_report_uses_actual_optimizer_graph(self):
        root = Path('/example')
        manifest = dict(carry_guidance_normalized=True, output_sha256={
            '/example/timing-graph.tsv': 'normalized', '/example/guidance-timing-graph.tsv': 'actual'})
        self.assertEqual(actual_native_graph(root, manifest), root / 'guidance-timing-graph.tsv')
        del manifest['output_sha256']['/example/guidance-timing-graph.tsv']
        with self.assertRaises(ValueError):
            actual_native_graph(root, manifest)

    def test_original_backend_uses_its_native_graph(self):
        root = Path('/example')
        self.assertEqual(actual_native_graph(root, {'output_sha256': {'/example/timing-graph.tsv': 'actual'}}),
                         root / 'timing-graph.tsv')


if __name__ == '__main__':
    unittest.main()
