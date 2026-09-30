import json
import unittest
from tools.synapse32_workload_report import compare, read_metrics


class WorkloadReportTest(unittest.TestCase):
    def record(self, cycles=100):
        return dict(schema=1, system_cycles=cycles, checked_results=35,
                    workload='test', memory_model='fixed', external_reads=2,
                    external_writes=1, external_read_bytes=8, external_write_bytes=1,
                    completed_transactions=3, request_stall_cycles=1,
                    response_latency_cycles=9)

    def test_read_and_compare(self):
        text = 'PASS Synapse32 variable-latency DRAM -> TPU:\nMETRICS ' + json.dumps(self.record())
        result = compare(read_metrics(text), self.record(50))
        self.assertEqual(result['same_clock_speedup'], 2)
        self.assertFalse(result['hardware_qualified'])

    def test_bad_or_multiple_runs(self):
        for text in ('', 'METRICS {}', 'PASS Synapse32 variable-latency DRAM -> TPU:\nMETRICS {}\nMETRICS {}'):
            with self.assertRaises(ValueError):
                read_metrics(text)

    def test_mismatch(self):
        for key, value in (('memory_model', 'different'), ('workload', 'different'),
                           ('checked_results', 34)):
            other = self.record()
            other[key] = value
            with self.assertRaises(ValueError):
                compare(self.record(), other)

    def test_mixed_and_truncated_logs(self):
        valid = 'PASS Synapse32 variable-latency DRAM -> TPU:\nMETRICS ' + json.dumps(self.record())
        for suffix in ('\nPASS Synapse32 variable-latency DRAM -> TPU:', '\nMETRICS {'):
            with self.assertRaises(ValueError):
                read_metrics(valid + suffix)

    def test_counter_validation(self):
        for key, value in (('schema', True), ('external_reads', -1),
                           ('external_write_bytes', '1'), ('completed_transactions', 0),
                           ('external_read_bytes', 0), ('external_write_bytes', 5)):
            record = self.record()
            record[key] = value
            with self.assertRaises(ValueError):
                read_metrics('PASS Synapse32 variable-latency DRAM -> TPU:\nMETRICS ' + json.dumps(record))
        record = self.record()
        del record['request_stall_cycles']
        with self.assertRaises(ValueError):
            read_metrics('PASS Synapse32 variable-latency DRAM -> TPU:\nMETRICS ' + json.dumps(record))

    def test_clock_tradeoff(self):
        result = compare(self.record(), self.record(200), 40, 100)
        self.assertEqual(result['hypothetical_speedup'], 1.25)
        self.assertEqual(result['hypothetical_baseline_ms'], 0.0025)
        self.assertEqual(result['hypothetical_candidate_ms'], 0.002)
        for clocks in ((40, None), (0, 100), (40, float('nan'))):
            with self.assertRaises(ValueError):
                compare(self.record(), self.record(), *clocks)


if __name__ == '__main__':
    unittest.main()
