#!/usr/bin/env python3
"""Separate unowned divider working data from start/cancel control."""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load("system_decode", "system-decode/run.py")
validation = load("system_mul_validation", "system-mul/run.py")


def prepare(out):
    overlay = base.prepare(out)
    path = overlay / "divider.v"
    original = path.read_text()
    (out / "divider_reference.v").write_text(original.replace("module divider (", "module divider_reference ("))
    payload = "dividend_q divisor_q quotient_q remainder_q dividend_negative_q quotient_negative_q signed_mode_q remainder_mode_q".split()
    source = original
    for name in payload:
        source, count = re.subn(r"^\s*" + name + r"\s*<=.*?;\n", "", source, flags=re.M | re.S)
        assert count >= 2, name
    marker = "    always @(posedge clk or posedge rst) begin"
    block = '''    // Working data is owned only while busy. Every accepted ordinary
    // launch initializes it at that same edge. A cancelled operation releases
    // ownership; speculative updates while idle or cancelling are unobservable.
    // Keep reset/start/cancel on busy, done, count and architectural result.
    always @(posedge clk) begin
        if (!busy) begin
            dividend_q <= (signed_mode && dividend[31]) ? (~dividend + 32'd1) : dividend;
            divisor_q <= (signed_mode && divisor[31]) ? (~divisor + 32'd1) : divisor;
            quotient_q <= 32'h0;
            remainder_q <= 33'h0;
            dividend_negative_q <= signed_mode && dividend[31];
            quotient_negative_q <= signed_mode && (dividend[31] ^ divisor[31]);
            signed_mode_q <= signed_mode;
            remainder_mode_q <= remainder_mode;
        end else begin
            dividend_q <= {dividend_q[30:0], 1'b0};
            quotient_q <= quotient_next;
            remainder_q <= remainder_next;
        end
    end

'''
    assert source.count(marker) == 1
    path.write_text(source.replace(marker, block + marker, 1))
    return overlay


def prove(out, overlay):
    inputs = {"clk":1,"rst":1,"start":1,"cancel":1,"signed_mode":1,"remainder_mode":1,"dividend":32,"divisor":32}
    outputs = {"busy":1,"done":1,"result":32}
    width = lambda n: "" if n == 1 else f"[{n-1}:0] "
    harness = "module divider_equiv(" + ",".join("input wire " + width(n) + p for p,n in inputs.items()) + ",output wire same);\n"
    for instance, module in (("gold","divider_reference"),("gate","divider")):
        harness += "\n".join("wire " + width(n) + instance + "_" + p + ";" for p,n in outputs.items()) + "\n"
        harness += module + " " + instance + "(" + ",".join("." + p + "(" + p + ")" for p in inputs) + "," + ",".join("." + p + "(" + instance + "_" + p + ")" for p in outputs) + ");\n"
    checks = [f"gold_{p}==gate_{p}" for p in outputs] + ["gold.count_q==gate.count_q"]
    owned = "dividend_q divisor_q quotient_q remainder_q dividend_negative_q quotient_negative_q signed_mode_q remainder_mode_q".split()
    checks += [f"!gold_busy || gold.{p}==gate.{p}" for p in owned]
    harness += "assign same=" + " && ".join("(" + c + ")" for c in checks) + ";\nendmodule\n"
    (out / "harness.sv").write_text(harness)
    script = f"read_slang --top divider_equiv {out / 'divider_reference.v'} {overlay / 'divider.v'} {out / 'harness.sv'}\n"
    script += "prep -top divider_equiv; flatten; async2sync; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 16 -set-init-zero -prove same 1 -verify;\n"
    (out / "proof.ys").write_text(script)
    with (out / "proof.log").open("w") as log:
        result = subprocess.run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys", "-Q", "-T", "-m", "slang", "-s", str(out / "proof.ys")], stdout=log, stderr=subprocess.STDOUT)
    paths = [overlay / "divider.v", out / "divider_reference.v", out / "harness.sv", out / "proof.ys", Path(__file__)]
    (out / "proof-results.json").write_text(json.dumps({"passed":result.returncode == 0,"sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2) + "\n")
    if result.returncode: raise SystemExit("Divider ownership proof failed: " + str(out / "proof.log"))
    print("PASS divider outputs, completion timing and all busy-owned working data under arbitrary inputs/reset/cancel", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare","prove","verify")); parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    overlay = prepare(out)
    if args.mode in ("prove","verify"): prove(out,overlay)
    if args.mode == "verify":
        validation.run(["iverilog","-g2012","-s","divider_tb","-o",out / "divider.vvp",overlay / "divider.v",HERE.parent / "divider/divider_tb.sv"],out / "divider-compile.log")
        validation.run(["vvp",out / "divider.vvp"],out / "divider.log")
        print((out / "divider.log").read_text(),flush=True)
        validation.verify(out,overlay,unit=False)
    paths = list(overlay.glob("*.v")) + [Path(__file__)]
    (out / (args.mode + "-sources.json")).write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2) + "\n")


if __name__ == "__main__": main()
