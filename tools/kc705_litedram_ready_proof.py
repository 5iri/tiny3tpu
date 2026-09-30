#!/usr/bin/env python3
"""Prove the actual generated eight-bank command chooser before/after factoring."""
import argparse
import json
from pathlib import Path
import subprocess

from migen.fhdl import verilog
from litex.soc.interconnect import stream
from litedram.common import cmd_request_rw_layout
from kc705_litedram_gen import install_local_ready


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--yosys", default=str(Path.home()/".apio/packages/oss-cad-suite/bin/yosys"))
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original, local, provenance = install_local_ready()
    for name, cls in [("original", original), ("local", local)]:
        requests = [stream.Endpoint(cmd_request_rw_layout(14, 3)) for _ in range(8)]
        dut = cls(requests)
        ios = set()
        # Give stable names by using the endpoint's flatten order.
        for i, request in enumerate(requests + [dut.cmd]):
            for j, field in enumerate(request.flatten()):
                field.name_override = "port{}_{}".format(i, j)
                ios.add(field)
        for field in (dut.want_reads, dut.want_writes, dut.want_cmds, dut.want_activates):
            ios.add(field)
        (out / (name + ".v")).write_text(str(verilog.convert(dut, ios=ios, name="chooser_"+name)))
    script = "\n".join([
        "read_verilog {}/original.v {}/local.v".format(out, out),
        "proc", "memory", "opt_clean",
        "equiv_make chooser_original chooser_local chooser_equiv",
        "hierarchy -top chooser_equiv", "equiv_simple", "equiv_induct -seq 4",
        "equiv_status -assert",
    ]) + "\n"
    (out / "proof.ys").write_text(script)
    with (out / "proof.log").open("w") as log:
        result = subprocess.run([a.yosys, "-Q", "-T", "-s", str(out/"proof.ys")],
                                stdout=log, stderr=subprocess.STDOUT)
    provenance["passed"] = result.returncode == 0
    (out / "proof.json").write_text(json.dumps(provenance, indent=2)+"\n")
    if result.returncode:
        print((out/"proof.log").read_text()[-6000:])
        raise SystemExit(result.returncode)
    print("PASS sequential equivalence: actual eight-bank chooser, all inputs and arbiter states")


if __name__ == "__main__":
    main()
