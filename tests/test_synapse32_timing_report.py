"""Actual nextpnr log spelling plus rejection/comparison regression fixtures."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tools.synapse32_timing_report import (
    CONTRACT, DERIVED_CLOCKS, FINAL_CLOCKS, HASH_KEYS, main, rank_reports, summarize,
)


def fixture(cpu=120.0, system=125.0):
    derived = "Info: Propagating clock constraints...\n"
    for clock, mhz in DERIVED_CLOCKS.items():
        through = "BUFGCE 'soc.clock_enable.cpu_global_clock'" if clock == "soc.cpu_clk" else "BUFG 'buffer'"
        derived += "Info:     derived {} MHz for net '{}' (through {})\n".format(mhz, clock, through)
    placement = "Info: Max frequency for clock        'soc.cpu_clk': 999.00 MHz (PASS at 100.00 MHz)\n"
    final = "Info: Router2 time 59.26s\nInfo: Running post-routing legalisation...\n"
    for clock, target in FINAL_CLOCKS.items():
        mhz = cpu if clock == "soc.cpu_clk" else system if clock == "clk" else 665.78
        final += "Info: Max frequency for clock {:>20}: {:.2f} MHz ({} at {:.2f} MHz)\n".format(
            "'" + clock + "'", mhz, "PASS" if mhz >= target else "FAIL", target)
    return derived + placement + final + "\nInfo: Max delay posedge soc.cpu_clk -> posedge clk        : 8.83 ns\nInfo: Slack histogram:\n1 warning, 0 errors\n"


def provenance():
    return dict({key: "a" * 64 for key in HASH_KEYS}, seed=4, threads=2, contract=CONTRACT)


class TimingReportTests(unittest.TestCase):
    def test_final_not_placement_and_no_signoff(self):
        report = summarize(fixture(), 0)
        self.assertTrue(report["accepted"])
        self.assertEqual(report["final_clocks"]["soc.cpu_clk"]["mhz"], 120)
        self.assertAlmostEqual(report["diagnostic_score"], 0.2)
        self.assertFalse(report["ddr_signoff"])
        self.assertEqual(len(report["cross_clock_delays"]), 1)
        self.assertEqual(report["clocks_worst_first"][0], "soc.cpu_clk")

    def test_actual_baseline_excerpt_exit_zero_trap(self):
        log = "Warning: set_property: target get_iobanks not supported (on line 486)\n" + fixture(6.29, 39.97)
        report = summarize(log, 0)
        self.assertTrue(report["completed"])
        self.assertFalse(report["accepted"])
        self.assertAlmostEqual(report["diagnostic_score"], -0.9371)
        self.assertTrue(any("constraint diagnostic" in r for r in report["reasons"]))
        self.assertEqual(sum("final timing failed" in r for r in report["reasons"]), 2)

    def test_related_cross_clock_paths_must_meet_budget(self):
        for text in ("14.83 ns", "10.01 ns", "nan ns"):
            report=summarize(fixture().replace("8.83 ns", text),0)
            self.assertFalse(report["accepted"])
            self.assertTrue(any("cross-clock" in reason for reason in report["reasons"]))
        report=summarize(fixture().replace("8.83 ns", "10.00 ns"),0)
        self.assertTrue(report["accepted"])
        self.assertEqual(report["cross_clock_delays"][0]["margin_ns"],0)
        # The reverse direction is checked too, and falling-edge registers
        # cannot borrow the full rising-to-rising period.
        reverse=fixture().replace("soc.cpu_clk -> posedge clk", "clk -> posedge soc.cpu_clk")
        self.assertFalse(summarize(reverse.replace("8.83 ns", "10.53 ns"),0)["accepted"])
        opposite=fixture().replace("-> posedge clk", "-> negedge clk")
        self.assertFalse(summarize(opposite,0)["accepted"])
        self.assertTrue(summarize(opposite.replace("8.83 ns", "4.83 ns"),0)["accepted"])

    def test_completion_required(self):
        for code in (None, 1, -9, 255):
            with self.subTest(code=code):
                self.assertFalse(summarize(fixture(), code)["accepted"])
        for marker in ("Info: Router2 time 59.26s\n", "Info: Running post-routing legalisation...\n"):
            self.assertFalse(summarize(fixture().replace(marker, ""), 0)["accepted"])
        self.assertFalse(summarize(fixture().split("Info: Router2")[0], 0)["accepted"])

    def test_missing_each_final_clock(self):
        for clock in FINAL_CLOCKS:
            log = "\n".join(line for line in fixture().splitlines()
                            if not ("Max frequency" in line and "'" + clock + "'" in line))
            self.assertFalse(summarize(log, 0)["accepted"], clock)

    def test_wrong_targets_and_missing_derivation(self):
        for log in (fixture().replace("at 100.00", "at 50.00"),
                    fixture().replace("derived 400.0", "derived 200.0"),
                    fixture().replace("BUFGCE", "BUFG"),
                    fixture().replace("net 'clk200'", "net 'other'")):
            self.assertFalse(summarize(log, 0)["accepted"])

    def test_last_block_cannot_borrow_missing_clocks(self):
        log = fixture() + "Info: Max frequency for clock 'clk': 150.00 MHz (PASS at 100.00 MHz)\n"
        self.assertFalse(summarize(log, 0)["accepted"])

    def test_errors_and_ignored_constraints(self):
        for warning in ("ERROR: failed to write FASM", "Warning: unsupported XDC command",
                        "Warning: create_clock target not found", "Warning: constraint propagation did not settle",
                        "nextpnr --timing-allow-fail", "nextpnr --force",
                        "Warning: set_max_delay unsupported", "1 warning, 2 errors"):
            self.assertFalse(summarize(fixture() + warning, 0)["accepted"], warning)

    def test_malformed_and_duplicate_reports(self):
        for suffix in ("Info: Max frequency for clock 'clk': nan MHz (PASS at 100.00 MHz)",
                       "Info: Propagating clock constraints..."):
            self.assertFalse(summarize(fixture() + suffix, 0)["accepted"])
        log = fixture().replace("\nInfo: Max delay", "\nInfo: Max frequency for clock 'clk': 120.00 MHz (PASS at 100.00 MHz)\nInfo: Max delay")
        self.assertFalse(summarize(log, 0)["accepted"])

    def test_placement_failure_does_not_override_final(self):
        log = fixture().replace("999.00 MHz (PASS", "9.00 MHz (FAIL")
        self.assertTrue(summarize(log, 0)["accepted"])

    def test_rank_and_provenance(self):
        slow = summarize(fixture(110), 0, provenance(), "slow")
        fast = summarize(fixture(120), 0, provenance(), "fast")
        fast["provenance"]["netlist_sha256"] = "b" * 64
        self.assertEqual(rank_reports([slow, fast])["ranking"], ["fast", "slow"])
        for key, value in (("seed", 5), ("xdc_sha256", "b" * 64), ("nextpnr_sha256", "c" * 64),
                           ("chipdb_sha256", "d" * 64), ("threads", 8), ("contract", "vexriscv")):
            altered = summarize(fixture(), 0, dict(provenance(), **{key: value}), "altered")
            self.assertEqual(rank_reports([slow, altered])["ranking"], [], key)
        self.assertEqual(rank_reports([summarize(fixture(), 0)])["ranking"], [])
        self.assertEqual(rank_reports([summarize(fixture(6.29), 0, provenance())])["ranking"], [])

    def test_cli(self):
        with tempfile.TemporaryDirectory(prefix="synapse32-timing-test-") as directory:
            path = Path(directory) / "route.log"
            path.write_text(fixture())
            for arguments, expected in (([str(path)], 1), ([str(path), "--exit-code", "0"], 0)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(arguments), expected)
                self.assertFalse(json.loads(output.getvalue())["reports"][0]["ddr_signoff"])


if __name__ == "__main__":
    unittest.main()
