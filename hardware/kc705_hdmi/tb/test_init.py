#!/usr/bin/env python3
"""Run the resolved open-drain KC705 mux/ADV7511 initialization simulation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build-kc705-hdmi/init"))
    parser.add_argument('--video-mode',choices=('vga','720p'),default='vga')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.out.resolve() / "test_init.vvp"
    sources = [root / "hardware/kc705_hdmi/src/kc705_hdmi_init.sv", Path(__file__).with_suffix(".sv")]
    evidence_files = [*sources, Path(__file__)]
    hashes = {str(p.resolve().relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in evidence_files}
    subprocess.run(["iverilog", "-g2012", "-Wall", "-s", "test_init", "-o", str(binary),
                    '-Ptest_init.VIDEO_720P='+str(int(args.video_mode=='720p')),
                    *map(str, sources)], check=True)
    result = subprocess.run(["vvp", str(binary)], text=True, capture_output=True)
    (args.out / "test_init.log").write_text(result.stdout + result.stderr)
    print(result.stdout, end="")
    print(result.stderr, end="")
    result.check_returncode()
    for path in evidence_files:
        key = str(path.resolve().relative_to(root))
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]:
            raise RuntimeError(f"source changed during simulation: {key}")
    (args.out / "report.json").write_text(json.dumps({
        "passed": True, "clock_hz": 74250000 if args.video_mode=='720p' else 25200000,
        "video_mode":args.video_mode, "maximum_i2c_hz": 100000,
        "scope": "resolved digital I2C pins and behavioral mux/transmitter; no physical board or HDMI video model",
        "source_sha256": hashes,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
