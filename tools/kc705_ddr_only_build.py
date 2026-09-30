#!/usr/bin/env python3
"""Build the CPU-free KC705 DDR3 test engine. Never programs the board."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "hardware/kc705_ddr_only"


def constraints(out, io_profile):
    from litex_boards.platforms.xilinx_kc705 import _io
    from litex.build.generic_platform import Pins, Subsignal, IOStandard, Misc
    lines = ["# Official LiteX KC705 pins; standalone DDR3 test engine."]

    def emit(port, items, inherited=(), limit=None):
        pins = next(x.identifiers for x in items if isinstance(x, Pins))[:limit]
        combined = list(inherited) + list(items)
        standard = next(x.name for x in reversed(combined) if isinstance(x, IOStandard))
        if io_profile == "experimental-sstl15" and port == "ddram_dq":
            if standard != "SSTL15_T_DCI":
                raise ValueError("Unexpected KC705 DQ standard")
            standard = "SSTL15"
        for i, pin in enumerate(pins):
            name = port if len(pins) == 1 else f"{port}[{i}]"
            lines.extend([f"set_property PACKAGE_PIN {pin} [get_ports {{{name}}}]",
                          f"set_property IOSTANDARD {standard} [get_ports {{{name}}}]"])
            for misc in (x.misc for x in combined if isinstance(x, Misc)):
                key, value = misc.split("=", 1)
                lines.append(f"set_property {key} {value} [get_ports {{{name}}}]")

    for name, number, *items in _io:
        if name == "user_led" and number < 8:
            emit(f"led[{number}]", items)
        elif name == "cpu_reset":
            emit("reset_btn", items)
        elif name in ("clk200", "ddram"):
            inherited = [x for x in items if not isinstance(x, Subsignal)]
            for part in (x for x in items if isinstance(x, Subsignal)):
                emit(("clk_" if name == "clk200" else "ddram_") + part.name,
                     part.constraints, inherited, 14 if name == "ddram" and part.name == "a" else None)
    lines.append("create_clock -period 5.000 [get_ports clk_p]")
    if io_profile == "dci":
        lines.append("set_property DCI_CASCADE {32 34} [get_iobanks 33]")
    (out / "kc705.xdc").write_text("\n".join(lines) + "\n")
    (out / "io-profile.json").write_text(json.dumps(dict(
        ddr_enabled=True, native_controller_enabled=True, profile=io_profile,
        fpga_dq_dci_termination=io_profile == "dci", hardware_only=True,
    ), indent=2) + "\n")


def generate(out):
    # Pin the PHY/controller APIs used by the hardware calibration engine.
    versions = {p: importlib.metadata.version(p) for p in ("litedram", "litex", "litex-boards", "migen")}
    if any(versions[p] != "2024.12" for p in ("litedram", "litex")):
        raise ValueError("Use the pinned LiteDRAM/LiteX 2024.12 environment")
    import litedram.gen as generator
    from litedram.init import get_ddr3_phy_init_sequence
    from kc705_litedram_gen import install_local_command_ready
    provenance = install_local_command_ready()
    config = json.loads("{" + (ROOT / "hardware/kc705_vexriscv/kc705_litedram.yml").read_text().split("{", 1)[1])
    config["user_ports"] = {"test": {"type": "wishbone", "data_width": 512, "block_until_ready": False}}
    (out / "litedram.json").write_text(json.dumps(config, indent=2) + "\n")
    settings = {}
    base = generator.LiteDRAMCore

    class StandaloneCore(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seq, _ = get_ddr3_phy_init_sequence(self.ddrphy.settings, self.sdram.controller.settings.timing)
            modes = {bank: value for comment, value, bank, _, _ in seq if comment.startswith("Load Mode Register")}
            settings.update(mr0=modes[0], mr1=modes[1], mr2=modes[2],
                            half_taps=self.ddrphy._half_sys8x_taps.storage.reset.value)

    generator.LiteDRAMCore = StandaloneCore
    argv = sys.argv
    try:
        sys.argv = ["litedram.gen", str(out / "litedram.json"), "--output-dir", str(out / "litedram"),
                    "--name", "kc705_dram"]
        generator.main()
    finally:
        sys.argv = argv
        generator.LiteDRAMCore = base
    sys.path.insert(0, str(HW))
    from engine import DDR3TestEngine
    from migen.fhdl import verilog
    regs = json.loads((out / "litedram/csr.json").read_text())["csr_registers"]
    engine = DDR3TestEngine(regs, **settings)
    # Explicit names make the generated module's public wires stable.
    ios = set()
    for prefix, bus in (("ctrl", engine.ctrl), ("mem", engine.mem)):
        for field in ("adr", "dat_w", "dat_r", "sel", "cyc", "stb", "we", "ack", "err"):
            signal = getattr(bus, field)
            signal.name_override = prefix + "_" + field
            ios.add(signal)
    for name in ("initialized", "calibrated", "passed", "failed", "busy", "failure_code",
                 "failure_address", "failure_lanes", "stage"):
        signal = getattr(engine, name)
        signal.name_override = name
        ios.add(signal)
    verilog.convert(engine, ios=ios, name="kc705_ddr_engine").write(str(out / "engine.v"))
    sources = [HW / "engine.py", HW / "kc705_ddr_only_top.sv", Path(__file__),
               ROOT / "tools/kc705_litedram_gen.py", out / "engine.v", out / "litedram/gateware/kc705_dram.v"]
    (out / "hardware-manifest.json").write_text(json.dumps(dict(
        target="kc705_ddr_only", cpu=False, firmware=False, tpu=False, dma=False, ethernet=False,
        controller_mhz=100, ddr_clock_mhz=400, settings=settings,
        generator_versions=versions, controller_transform=provenance,
        simulation=False, hardware_memory_pass=False,
        sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    ), indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["generate", "synth", "route"])
    p.add_argument("--build-dir", type=Path, default=ROOT / "build-ddr-only")
    p.add_argument("--ddr-io", choices=["dci", "experimental-sstl15"], default="dci")
    p.add_argument("--yosys", type=Path, default=Path.home() / ".apio/packages/oss-cad-suite/bin/yosys")
    p.add_argument("--nextpnr", type=Path, default=ROOT / "build-vexriscv/nextpnr-preg-grade2/nextpnr-xilinx")
    p.add_argument("--chipdb", type=Path, default=Path("/tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin"))
    p.add_argument("--seed", type=int, default=4)
    a = p.parse_args()
    out = a.build_dir.resolve()
    if a.stage == "route" and (not a.chipdb.is_file() or not a.nextpnr.is_file()):
        p.error("Routing requires an existing --chipdb and --nextpnr executable")
    if any(c.isspace() or c in '\";\\' for path in (out, ROOT) for c in str(path)):
        p.error("Yosys paths must not contain spaces, quotes, or separators")
    out.mkdir(parents=True, exist_ok=True)

    def run(command, name):
        print(f"Running {name}: {out / (name+'.log')}", flush=True)
        with (out / (name+".log")).open("w") as log:
            result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            print((out / (name+".log")).read_text()[-6000:], file=sys.stderr)
            raise SystemExit(result.returncode)

    # Keep verbose LiteX generation separate from the command's status output.
    from contextlib import redirect_stdout, redirect_stderr
    with (out / "generate.log").open("w") as log, redirect_stdout(log), redirect_stderr(log):
        generate(out)
    constraints(out, a.ddr_io)
    print(f"Generated CPU-free DDR3 target: {out}", flush=True)
    if a.stage == "generate":
        return
    script = [f"read_verilog -sv {HW / 'kc705_ddr_only_top.sv'} {out / 'engine.v'} {out / 'litedram/gateware/kc705_dram.v'}",
              "read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v",
              "hierarchy -check -top kc705_ddr_only_top",
              # Upstream repeats the identical DFI mask assignment per phase;
              # merge identical cells before checking for conflicting drivers.
              "proc; opt; check -assert",
              # The first route's bank-ready path crossed cascaded LUT7/8
              # muxes; keep this DDR-only target in ordinary LUT6 fabric.
              f"synth_xilinx -family xc7 -nowidelut -flatten -top kc705_ddr_only_top -json {out / 'soc.json'}",
              "check -assert", "stat"]
    (out / "synth.ys").write_text("\n".join(script)+"\n")
    run([a.yosys, "-Q", "-T", "-s", out / "synth.ys"], "synth")
    if a.stage == "synth":
        return
    clocks = [("clk200", 200), ("clk", 100), ("memory.sys_clk", 100),
              ("memory.sys4x_clk", 400), ("memory.iodelay_clk", 200)]
    (out / "clocks.py").write_text(f"for name, mhz in {clocks!r}:\n    ctx.addClock(name, mhz)\n")
    run([a.nextpnr, "--chipdb", a.chipdb, "--xdc", out / "kc705.xdc", "--freq", "100",
         "--seed", a.seed, "--pre-pack", out / "clocks.py", "--json", out / "soc.json",
         "--write", out / "soc_routed.json", "--fasm", out / "soc.fasm"], "route")
    from kc705_open_build import validate_route_log
    try:
        validate_route_log((out / "route.log").read_text())
    except ValueError as error:
        raise SystemExit(f"Route rejected: {error}. The output is not a board candidate.")
    print("Route guard passed; hardware memory testing is still required.")


if __name__ == "__main__":
    main()
