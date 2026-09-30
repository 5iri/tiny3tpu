#!/usr/bin/env python3
"""Prove the complete four-phase, eight-bank command multiplexer transformation."""
import argparse
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from migen import Signal
from migen.fhdl import verilog
from litex.soc.interconnect import stream
from litedram.common import cmd_request_rw_layout
from litedram.core.controller import ControllerSettings
from litedram.modules import MT8JTF12864
from litedram.phy import dfi
import litedram.core.multiplexer as multiplexer
from kc705_litedram_gen import install_local_command_ready


def circuit(sys_clk_freq=100e6, read_latency=8):
    module = MT8JTF12864(sys_clk_freq, "1:4")
    settings = ControllerSettings()
    settings.geom = module.geom_settings
    settings.timing = module.timing_settings
    settings.phy = SimpleNamespace(nphases=4, rdphase=Signal(2), wrphase=Signal(2),
                                   cwl=5, read_latency=read_latency, dfi_databits=128)
    banks = [SimpleNamespace(cmd=stream.Endpoint(cmd_request_rw_layout(14, 3)),
                             refresh_req=Signal(), refresh_gnt=Signal()) for _ in range(8)]
    refresher = SimpleNamespace(cmd=stream.Endpoint(cmd_request_rw_layout(14, 3)))
    bus = SimpleNamespace(wdata=Signal(512), wdata_we=Signal(64), rdata=Signal(512))
    phy = dfi.Interface(14, 3, 1, 128, nphases=4)
    dut = multiplexer.Multiplexer(settings, banks, refresher, phy, bus)
    ports = [settings.phy.rdphase, settings.phy.wrphase, bus.wdata, bus.wdata_we, bus.rdata]
    for bank in banks:
        ports += list(bank.cmd.flatten()) + [bank.refresh_req, bank.refresh_gnt]
    ports += list(refresher.cmd.flatten()) + list(phy.flatten())
    for i, signal in enumerate(ports):
        signal.name_override = "port_" + str(i)
    return dut, set(ports)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--sys-clk-freq", type=float, default=100e6)
    p.add_argument("--read-latency", type=int, default=8)
    p.add_argument("--yosys", default=str(Path.home()/".apio/packages/oss-cad-suite/bin/yosys"))
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dut, ports = circuit(a.sys_clk_freq, a.read_latency)
    (out/"original.v").write_text(str(verilog.convert(dut, ios=ports, name="original")))
    record = install_local_command_ready()
    record["sys_clk_freq"] = a.sys_clk_freq
    record["read_latency"] = a.read_latency
    dut, ports = circuit(a.sys_clk_freq, a.read_latency)
    (out/"local.v").write_text(str(verilog.convert(dut, ios=ports, name="local")))
    script = "\n".join([
        "read_verilog {}/original.v {}/local.v".format(out, out),
        "proc", "memory", "opt_clean", "equiv_make original local equivalent",
        "hierarchy -top equivalent", "equiv_simple", "equiv_induct -seq 4", "equiv_status -assert",
    ]) + "\n"
    (out/"proof.ys").write_text(script)
    with (out/"proof.log").open("w") as log:
        result = subprocess.run([a.yosys, "-Q", "-T", "-s", str(out/"proof.ys")],
                                stdout=log, stderr=subprocess.STDOUT)
    record["passed"] = result.returncode == 0
    (out/"proof.json").write_text(json.dumps(record, indent=2)+"\n")
    if result.returncode:
        print((out/"proof.log").read_text()[-7000:])
        raise SystemExit(result.returncode)
    print("PASS complete KC705 command multiplexer sequential equivalence")


if __name__ == "__main__":
    main()
