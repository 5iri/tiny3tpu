"""Regression for build input validation and zero-exit timing/XDC failures."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "kc705_build", Path(__file__).resolve().parents[1] / "tools/kc705_open_build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class RouteGuardTest(unittest.TestCase):
    def test_timing_failure(self):
        with self.assertRaisesRegex(ValueError, "timing failed"):
            builder.validate_route_log(
                "Info: Max frequency for clock 'sys': 75.95 MHz (FAIL at 125.00 MHz)")

    def test_ignored_dci(self):
        with self.assertRaisesRegex(ValueError, "XDC"):
            builder.validate_route_log(
                "Warning: set_property: target get_iobanks not supported (on line 486)")

    def test_pass_is_not_rejected(self):
        builder.validate_route_log(
            "Info: Max frequency for clock 'sys': 140.00 MHz (PASS at 125.00 MHz)")

    def test_routed_result_supersedes_placement_estimate(self):
        builder.validate_route_log(
            "Info: Max frequency for clock 'sys': 90.00 MHz (FAIL at 100.00 MHz)\n"
            "Info: Max frequency for clock 'sys': 105.00 MHz (PASS at 100.00 MHz)")

    def test_other_clock_failure_is_retained(self):
        with self.assertRaisesRegex(ValueError, "timing failed"):
            builder.validate_route_log(
                "Info: Max frequency for clock 'sys': 90.00 MHz (FAIL at 100.00 MHz)\n"
                "Info: Max frequency for clock 'io': 205.00 MHz (PASS at 200.00 MHz)")

    def test_missing_clock_report(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            builder.validate_route_log("0 warnings, 0 errors")

    def test_ignored_clock(self):
        with self.assertRaisesRegex(ValueError, "clock constraint"):
            builder.validate_route_log("Warning: net 'sys' does not exist, ignoring clock constraint")


@unittest.skipUnless(shutil.which("cmake"), "CMake is required")
class CpuOverlayValidationTest(unittest.TestCase):
    def check_rejected(self, directory_source):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="tiny3tpu-overlay-test-") as temp:
            work = Path(temp)
            cpu = work / "cpu"
            core = cpu / "rtl/core_modules"
            core.mkdir(parents=True)
            for name in ("alu", "divider"):
                (core / (name + ".v")).touch()
            for name in ("riscv_cpu", "execution_unit", "memory_unit", "writeback"):
                (cpu / "rtl" / (name + ".v")).touch()
            overlay = work / "overlay"
            overlay.mkdir()
            if directory_source:
                (overlay / "riscv_cpu.v").mkdir()
            output = work / "must-not-exist"
            result = subprocess.run([
                shutil.which("cmake"), "-DSOURCE_DIR=" + str(root),
                "-DBINARY_DIR=" + str(output), "-DSYNAPSE32_DIR=" + str(cpu),
                "-DCPU_OVERLAY_DIR=" + str(overlay), "-DVERILATOR=unused",
                "-DRISCV_GCC=unused", "-DRISCV_OBJCOPY=unused",
                "-P", str(root / "tests/run_synapse32_cpu_test.cmake"),
            ], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Incomplete CPU overlay: riscv_cpu", result.stderr)
            self.assertFalse(output.exists(), "Invalid input created build output")
            result = subprocess.run([
                sys.executable, str(root / "tools/kc705_open_build.py"),
                "generate", "--synapse32-dir", str(cpu),
                "--cpu-overlay-dir", str(overlay), "--build-dir", str(output),
            ], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Overlay needs exactly one original and replacement for riscv_cpu.v",
                          result.stderr)
            self.assertFalse(output.exists(), "Invalid input created build output")

    def test_missing_overlay_rejected_before_writes(self):
        self.check_rejected(directory_source=False)

    def test_directory_source_rejected_before_writes(self):
        self.check_rejected(directory_source=True)


if __name__ == "__main__":
    unittest.main()
