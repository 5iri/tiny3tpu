#!/usr/bin/env python3
"""Reproducible open-source KC705 build; no Vivado/MIG and no implicit flashing.

Run with the isolated Python 3.9 environment containing pinned LiteDRAM/LiteX.
Generated RTL uses LiteDRAM's standalone generator (gateware compilation off).
The actual implementation commands are Yosys and openXC7 nextpnr.
"""
import argparse
import importlib.metadata
from pathlib import Path
import subprocess
import sys
import re
import json

ROOT = Path(__file__).resolve().parents[1]


def validate_route_log(route_log):
    """Reject known failures even when the installed router exits zero.

    This is a rejection filter, not proof of complete timing/IO coverage.
    """
    if any("set_property" in line and "not supported" in line
           for line in route_log.splitlines()):
        raise ValueError("nextpnr ignored an XDC property")
    if "ignoring clock constraint" in route_log:
        raise ValueError("nextpnr ignored a clock constraint")
    if re.search(r"^ERROR:", route_log, re.MULTILINE):
        raise ValueError("nextpnr reported an implementation error")
    # nextpnr prints an estimate after placement and another after routing.
    # Judge the last report for every clock, retaining failures for any clock
    # that disappeared from a later report. Never accept a missing report.
    clocks = {}
    for clock, result in re.findall(
            r"Max frequency for clock\s+'([^']+)': [0-9.]+ MHz \((PASS|FAIL) at [0-9.]+ MHz\)", route_log):
        clocks[clock] = result
    if not clocks:
        raise ValueError("timing report is missing")
    if any(result != "PASS" for result in clocks.values()):
        raise ValueError("timing failed despite nextpnr's exit status")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["generate", "firmware", "synth", "route"])
    parser.add_argument("--synapse32-dir", type=Path, required=True)
    parser.add_argument("--cpu", choices=["synapse32", "vexriscv-lite"], default="synapse32",
                        help="VexRiscv uses the Synapse32 checkout only for its UART")
    parser.add_argument("--cpu-overlay-dir", type=Path,
                        help="Experimental four-file divider integration overlay; upstream stays unchanged")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-ddr")
    parser.add_argument("--firmware-source", type=Path,
                        help="Custom no-DDR firmware C source (same startup and mailbox drivers)")
    parser.add_argument("--firmware-include", type=Path,
                        help="Additional include directory for custom no-DDR firmware")
    parser.add_argument("--yosys", default=str(Path.home() / ".apio/packages/oss-cad-suite/bin/yosys"))
    parser.add_argument("--gcc", default="riscv64-unknown-elf-gcc")
    parser.add_argument("--objcopy", default="riscv64-unknown-elf-objcopy")
    parser.add_argument("--nextpnr", help="Router executable; VexRiscv defaults to the locally qualified DSP timing build")
    parser.add_argument("--chipdb", type=Path, default=Path("/tmp/openxc7-blinky-full/xc7k325tffg900-2-apio.bin"))
    parser.add_argument("--seed", type=int, default=None,
                        help="nextpnr placer/router seed; omit for the router default")
    parser.add_argument("--lut6", action="store_true",
                        help="Limit synthesis to LUT6; avoid long chains through dedicated LUT7/8 muxes")
    parser.add_argument("--ddr-stress", action="store_true",
                        help="Add destructive 2 MiB/eight-window DDR stress to VexRiscv boot firmware")
    parser.add_argument("--ddr-cdc", action="store_true",
                        help="CPU/TPU at 100 MHz, DDR controller at 83 1/3 MHz, with a handshake bridge")
    parser.add_argument("--ddr-controller-mhz", type=float, default=None,
                        help="Override --ddr-cdc controller rate: 83.333 or 100 MHz")
    parser.add_argument("--diagnostic-cpu-mhz", type=float, choices=[50, 62.5, 100], default=100,
                        help="Slow the CPU/TPU for PHY diagnosis; requires --ddr-cdc --ddr-debug")
    parser.add_argument("--ddr-debug", action="store_true",
                        help="Check PHY CSR readback and capture DDR3 MPR reads after calibration failure")
    parser.add_argument("--ddr-trace", action="store_true",
                        help="Add a sixteen-cycle DFI read history; requires --ddr-cdc --ddr-debug")
    parser.add_argument("--ddr-phy-only", action="store_true",
                        help="Diagnostic: remove the native controller and test only the software-controlled PHY")
    parser.add_argument("--ddr-read-latency-offset", type=int, choices=[-2,-1,0,1], default=0,
                        help="Diagnostic change to K7 PHY read-valid latency; requires --ddr-cdc")
    parser.add_argument("--allow-const-holdouts", action="store_true",
                        help="Pass NEXTPNR_ALLOW_CONST_HOLDOUTS=1 for timing diagnostics only; "
                             "the route guard still rejects the output for bitstream use")
    parser.add_argument("--no-ddr", action="store_true",
                        help="DDR-free KC705 bring-up variant (kc705_noddr_top, boot-RAM-only "
                             "firmware); no LiteDRAM, DDR pins, or DCI constraints")
    parser.add_argument("--ddr-io", choices=["dci", "experimental-sstl15"], default="dci",
                        help="Stock DCI termination, or explicit unterminated FPGA-input experiment "
                             "matching openXC7's KC705 DDR demo; the latter needs hardware qualification")
    parser.add_argument("--freq", type=float, default=100.0,
                        help="nextpnr target MHz (Synapse32 no-DDR PLL is 40 MHz; VexRiscv is 100 MHz)")
    parser.add_argument("--system-overlay-dir", type=Path,
                        help="Experimental board-RTL overlay (named file replacement, "
                             "upstream stays unchanged); default build uses production sources")
    args = parser.parse_args()
    if (args.firmware_source or args.firmware_include) and not args.no_ddr:
        parser.error("custom firmware requires --no-ddr")
    vex = args.cpu == "vexriscv-lite"
    if args.ddr_stress and (args.no_ddr or not vex):
        parser.error("--ddr-stress requires the VexRiscv DDR build")
    if args.ddr_cdc and (args.no_ddr or not vex):
        parser.error("--ddr-cdc requires the VexRiscv DDR build")
    if args.ddr_debug and (args.no_ddr or not vex):
        parser.error("--ddr-debug requires the VexRiscv DDR build")
    if args.ddr_read_latency_offset and not args.ddr_cdc:
        parser.error("--ddr-read-latency-offset requires --ddr-cdc")
    if args.ddr_trace and not (args.ddr_cdc and args.ddr_debug):
        parser.error("--ddr-trace requires --ddr-cdc --ddr-debug")
    if args.ddr_phy_only and (not (args.ddr_cdc and args.ddr_debug) or args.ddr_stress):
        parser.error("--ddr-phy-only requires --ddr-cdc --ddr-debug and excludes --ddr-stress")
    if args.ddr_controller_mhz is not None and not args.ddr_cdc:
        parser.error("--ddr-controller-mhz requires --ddr-cdc")
    if args.diagnostic_cpu_mhz != 100 and not (args.ddr_cdc and args.ddr_debug):
        parser.error("--diagnostic-cpu-mhz requires --ddr-cdc --ddr-debug")
    dram_mhz = 1000/12
    if args.ddr_controller_mhz is not None:
        if abs(args.ddr_controller_mhz - 1000/12) < 0.001:
            dram_mhz = 1000/12
        elif args.ddr_controller_mhz == 100:
            dram_mhz = 100
        else:
            parser.error("The supported DDR controller rates are 83.333 and 100 MHz")
    if args.ddr_io != "dci" and (args.no_ddr or not vex):
        parser.error("The experimental DDR IO profile is only for the VexRiscv DDR build")
    if args.nextpnr is None:
        args.nextpnr = str(ROOT / "build-vexriscv/nextpnr-preg-grade2/nextpnr-xilinx" if vex else
                           Path.home() / ".apio/packages/openxc7/libexec/nextpnr-xilinx")
        if vex and args.stage == "route" and not Path(args.nextpnr).is_file():
            parser.error("Build the KC705 DSP timing router or supply --nextpnr; see hardware/kc705_vexriscv/README.md")
    if vex and (args.cpu_overlay_dir or args.system_overlay_dir):
        parser.error("Synapse32 overlays do not apply to VexRiscv")
    if vex and args.freq != 100:
        parser.error("VexRiscv board PLL, DDR and firmware are configured for 100 MHz")
    build = args.build_dir.resolve()
    cpu = args.synapse32_dir.resolve()
    overlay = args.cpu_overlay_dir.resolve() if args.cpu_overlay_dir else None
    system_overlay = args.system_overlay_dir.resolve() if args.system_overlay_dir else None
    checked_paths = (cpu, build, ROOT) + tuple(p for p in (overlay, system_overlay) if p)
    if any(c.isspace() or c in '\";\\' for path in checked_paths for c in str(path)):
        parser.error("Yosys include path requires a checkout path without spaces, quotes or separators")
    required_cpu_file = "rtl/core_modules/uart.v" if vex else "rtl/riscv_cpu.v"
    if not (cpu / required_cpu_file).is_file():
        parser.error("--synapse32-dir must contain " + required_cpu_file)
    cpu_sources = sorted((cpu / "rtl/core_modules").glob("*.v"))
    cpu_sources += sorted((cpu / "rtl/pipeline_stages").glob("*.v"))
    cpu_sources += [cpu / "rtl" / (name + ".v")
                   for name in ("riscv_cpu", "execution_unit", "memory_unit", "writeback")]
    if overlay:
        replacements = {name: overlay / name for name in
                        ("riscv_cpu.v", "execution_unit.v", "alu.v", "divider.v")}
        for name, path in replacements.items():
            if not path.is_file() or sum(s.name == name for s in cpu_sources) != 1:
                parser.error("Overlay needs exactly one original and replacement for " + name)
        cpu_sources = [replacements.get(s.name, s) for s in cpu_sources]
    build.mkdir(parents=True, exist_ok=True)

    def run(command, name, env=None):
        logfile = build / (name + ".log")
        print("Running {} (log: {})".format(name, logfile), flush=True)
        with logfile.open("w") as log:
            result = subprocess.run([str(x) for x in command], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    env=env)
        if result.returncode:
            print("\n".join(logfile.read_text(errors="replace").splitlines()[-35:]), file=sys.stderr)
            raise SystemExit(result.returncode)

    versions = {name: importlib.metadata.version(name)
                for name in ("litedram", "litex", "litex-boards", "migen", "pyyaml")}
    (build / "generator-versions.txt").write_text(
        "\n".join("{}=={}".format(k, v) for k, v in versions.items()) + "\n")
    if versions["litedram"] != "2024.12" or versions["litex"] != "2024.12":
        parser.error("This build is qualified only for LiteDRAM/LiteX 2024.12")
    if not args.no_ddr:
        dram_config = ROOT / "hardware" / ("kc705_vexriscv" if vex else "synapse32") / "kc705_litedram.yml"
        generator = [ROOT / "tools/kc705_litedram_gen.py"] if vex else ["-m", "litedram.gen"]
        if args.ddr_cdc:
            config = json.loads("{" + dram_config.read_text().split("{", 1)[1])
            config.update(sys_clk_freq=dram_mhz*1e6, cpu_clk_freq=args.diagnostic_cpu_mhz*1e6,
                          read_latency_offset=args.ddr_read_latency_offset,
                          debug_read_trace=args.ddr_trace,
                          debug_phy_only=args.ddr_phy_only)
            dram_config = build / "litedram-cdc.json"
            dram_config.write_text(json.dumps(config, indent=2) + "\n")
            generator = [ROOT / "tools/kc705_litedram_gen_async.py"]
        run([sys.executable] + generator + [dram_config,
             "--output-dir", build / "litedram", "--name", "kc705_dram"], "generate")

    # Generate physical constraints from the installed official board package.
    # Do not use the standalone generator's placeholder LOC=X constraints.
    from litex_boards.platforms.xilinx_kc705 import _io
    from litex.build.generic_platform import Pins, Subsignal, IOStandard, Misc
    lines = ["# Derived from LiteX-Boards xilinx_kc705 (BSD-2-Clause)."]
    if not args.no_ddr:
        lines += ["# DDR IO profile: " + args.ddr_io]
        if args.ddr_io == "experimental-sstl15":
            lines += ["# EXPERIMENT: plain SSTL15 DQ, no FPGA DCI termination/cascade.",
                      "# Matches openXC7/demo-projects litex-ddr-kc705; not stock KC705 termination.",
                      "# Requires calibration and memory stress on the actual board."]
        else:
            lines += ["# Stock DCI termination; unsupported constraints remain fatal."]
    (build / "io-profile.json").write_text(json.dumps({
        "ddr_enabled": not args.no_ddr,
        "native_controller_enabled": not args.no_ddr and not args.ddr_phy_only,
        "profile": args.ddr_io if not args.no_ddr else None,
        "fpga_dq_dci_termination": not args.no_ddr and args.ddr_io == "dci",
        "reference": "https://github.com/openXC7/demo-projects/blob/7cfd51ed5e881721d54954c6ae5966535912117f/litex-ddr-kc705/xilinx_kc705.xdc"
                     if args.ddr_io == "experimental-sstl15" else None,
    }, indent=2) + "\n")

    def emit(port, constraints, inherited=(), limit=None):
        all_constraints = list(inherited) + list(constraints)
        pins = next(x.identifiers for x in constraints if isinstance(x, Pins))
        if limit is not None:
            pins = pins[:limit]
        standard = next(x.name for x in reversed(all_constraints) if isinstance(x, IOStandard))
        if args.ddr_io == "experimental-sstl15" and port == "ddram_dq":
            assert standard == "SSTL15_T_DCI"
            standard = "SSTL15"
        misc = [x.misc for x in all_constraints if isinstance(x, Misc)]
        for index, pin in enumerate(pins):
            name = port if len(pins) == 1 else "{}[{}]".format(port, index)
            lines.append("set_property PACKAGE_PIN {} [get_ports {{{}}}]".format(pin, name))
            lines.append("set_property IOSTANDARD {} [get_ports {{{}}}]".format(standard, name))
            for item in misc:
                key, value = item.split("=", 1)
                lines.append("set_property {} {} [get_ports {{{}}}]".format(key, value, name))

    for resource in _io:
        name, number, *constraints = resource
        if name == "user_led":
            emit("led[{}]".format(number), constraints)
        elif name == "cpu_reset":
            emit("reset_btn", constraints)
        elif name in ("clk200", "serial") or (name == "ddram" and not args.no_ddr):
            inherited = [x for x in constraints if not isinstance(x, Subsignal)]
            for signal in constraints:
                if not isinstance(signal, Subsignal):
                    continue
                if name == "serial" and signal.name not in ("tx", "rx"):
                    continue
                port = ("clk_" if name == "clk200" else "uart_" if name == "serial" else "ddram_") + signal.name
                emit(port, signal.constraints, inherited,
                     14 if name == "ddram" and signal.name == "a" else None)
    lines += ["create_clock -period 5.000 [get_ports clk_p]"]
    if not args.no_ddr and args.ddr_io == "dci":
        lines += ["set_property DCI_CASCADE {32 34} [get_iobanks 33]"]
    (build / "kc705.xdc").write_text("\n".join(lines) + "\n")
    if args.stage == "generate":
        return

    import litex
    software = Path(litex.__file__).resolve().parent / "soc/software"
    firmware = ROOT / "hardware/synapse32"
    cflags = [args.gcc, "-march=rv32im_zicsr_zifencei" if vex else "-march=rv32i_zicsr_zifencei", "-mabi=ilp32", "-Os",
              "-ffreestanding", "-fno-builtin", "-ffunction-sections", "-fdata-sections",
              "-nostdlib", "-msmall-data-limit=0", "-Wall", "-Wextra"]
    if args.ddr_stress:
        cflags += ["-DTINY3TPU_DDR_STRESS", ROOT / "hardware/kc705_vexriscv/ddr_stress.c"]
    if args.ddr_cdc:
        cflags += ["-DTINY3TPU_CPU_CLOCK_FREQUENCY={}UL".format(int(args.diagnostic_cpu_mhz*1e6))]
    if args.ddr_debug:
        cflags += ["-DTINY3TPU_DDR_DEBUG", ROOT / "hardware/kc705_vexriscv/ddr_phy_debug.c"]
    if args.ddr_phy_only:
        cflags += ["-DTINY3TPU_DDR_PHY_ONLY"]
    if args.no_ddr:
        # Boot-RAM-only bring-up: UART + TPU self-test, no LiteDRAM.
        # Match the board PLL: Synapse32 40 MHz, VexRiscv 100 MHz.
        cflags += ["-DCONFIG_CLOCK_FREQUENCY={}UL".format(100000000 if vex else 40000000),
                   "-I" + str(ROOT / "include"), "-I" + str(firmware),
                   "-Wl,--no-relax,--gc-sections", "-T" + str(firmware / "bringup.ld"),
                   firmware / "start.S", (args.firmware_source.resolve() if args.firmware_source else firmware / "noddr_selftest.c"),
                   ROOT / "src/axis_mailbox.c", ROOT / "src/mmio_backend.c",
                   "-lgcc", "-o", build / "firmware.elf"]
        if args.firmware_include:
            cflags += ["-I" + str(args.firmware_include.resolve())]
    else:
        cflags += ["-DTINY3TPU_DRAM_SMOKE", "-DTINY3TPU_DDR_CALIBRATION",
                   "-DCSR_BASE=0xf0000000UL", "-DMAIN_RAM_BASE=0x40000000UL",
                   "-DMEMTEST_DATA_SIZE=16384",
                   "-I" + str(ROOT / "include"), "-I" + str(firmware),
                   "-I" + str(build / "litedram/software/include"),
                   "-I" + str(software / "include"), "-I" + str(software),
                   "-Wl,--no-relax,--gc-sections", "-T" + str(firmware / "bringup.ld"),
                   firmware / "start.S", firmware / "stream_smoke.c",
                   firmware / "dram_selftest.c", firmware / "ddr_boot_support.c",
                   software / "liblitedram/sdram.c", software / "liblitedram/accessors.c",
                   ROOT / "src/axis_mailbox.c", ROOT / "src/mmio_backend.c",
                   "-lgcc", "-o", build / "firmware.elf"]
    run(cflags, "firmware")
    run([args.objcopy, "-O", "verilog", "--verilog-data-width=4", "--change-addresses=-0x80000000",
         build / "firmware.elf", build / "firmware.hex"], "image")
    if args.stage == "firmware":
        return

    top = "kc705_noddr_top" if args.no_ddr else "kc705_synapse32_top"
    sources = [cpu / "rtl/core_modules/uart.v"]
    board_blocks = ["synapse32_clock_enable", "synapse32_memory_sequencer", "synapse32_dram_soc"]
    if args.no_ddr:
        board_blocks += ["kc705_noddr_top"]
    else:
        board_blocks += ["litedram_wishbone_bridge", "kc705_synapse32_top"]
    sources += [firmware / (name + ".sv") for name in board_blocks]
    if vex:
        top = "kc705_vexriscv_noddr_top" if args.no_ddr else "kc705_vexriscv_top"
        sources = [cpu / "rtl/core_modules/uart.v",
                   ROOT / "third_party/vexriscv/VexRiscv_Lite.v",
                   ROOT / "hardware/kc705_vexriscv/vexriscv_tpu_soc.sv",
                   ROOT / "hardware/kc705_vexriscv" / (top + ".sv")]
        if not args.no_ddr:
            sources += [firmware / "litedram_wishbone_bridge.sv",
                        ROOT / "hardware/kc705_vexriscv/litedram_wishbone32_to512.sv"]
            if args.ddr_cdc:
                sources += [ROOT / "hardware/kc705_vexriscv/req_resp_cdc.sv"]
    if system_overlay:
        # Named replacement only: every overlay file must match a board
        # source by basename (basenames are unique); nothing may be added.
        board_names = {s.name for s in sources}
        overlay_files = sorted(system_overlay.glob("*.sv"))
        if not overlay_files or any(s.name not in board_names for s in overlay_files):
            parser.error("--system-overlay-dir must hold only board-RTL basenames")
        by_name = {s.name: s for s in overlay_files}
        sources = [by_name.get(s.name, s) for s in sources]
    sources += [ROOT / "multi-core" / name for name in (
        "synapse32_tpu_peripheral.sv", "synapse32_axis_mailbox.sv",
        "tiny3tpu_axis.sv", "tiny3tpu_axis_bridge.sv", "tiny3tpu_axi.sv",
        "top.v", "tpu_core_wrapper.sv")]
    sources += [ROOT / "systolic_array/rtl/NxN_systolic_array.v", ROOT / "systolic_array/rtl/pe.v"]
    if not args.no_ddr:
        sources += [build / "litedram/gateware/kc705_dram.v"]
    def quote(path):
        return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'
    # Slang elaborates the CPU's cross-module CSR references correctly. The
    # classic Yosys Verilog frontend rejects them; never turn them into undriven wires.
    boot_header = build / "boot_path.vh"
    boot_header.write_text("`define {}_BOOT_HEX {}\n".format(
        "VEXRISCV" if vex else "SYNAPSE32", quote(build / "firmware.hex")))
    if args.ddr_cdc:
        boot_header.write_text(boot_header.read_text() + "`define VEXRISCV_DDR_CDC\n")
    if args.ddr_phy_only:
        boot_header.write_text(boot_header.read_text() + "`define VEXRISCV_DDR_PHY_ONLY\n")
    script = [] if vex else ["read_slang --allow-use-before-declare --single-unit --top riscv_cpu -I{} {}".format(
                  cpu / "rtl/include", " ".join(map(str, cpu_sources)))]
    script += [
              # Slang handles CPU hierarchical references; the classic frontend
              # handles inferred boot RAM and parameterized FPGA primitives.
              "read_verilog -sv -I{} {} {}".format(
                  cpu / "rtl/include", boot_header, " ".join(map(str, sources))),
              "read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v",
              "hierarchy -check -top {}".format(top),
              "synth_xilinx -family xc7 -flatten {} -top {} -json {}".format(
                  "-nowidelut" if args.lut6 else "", top, quote(build / "soc.json")),
              "check -assert", "stat"]
    (build / "synth.ys").write_text("\n".join(script) + "\n")
    run([args.yosys, "-Q", "-T", "-m", "slang", "-s", build / "synth.ys"], "synth")
    if args.stage == "synth":
        return
    if not args.chipdb.is_file():
        parser.error("Missing Kintex-7 chip database")
    # Never allow a timing failure to masquerade as a valid board image.
    import os
    route_command = [args.nextpnr, "--chipdb", args.chipdb, "--xdc", build / "kc705.xdc",
                     "--freq", str(args.freq)]
    if vex:
        # This backend does not reliably infer generated clock frequencies.
        clocks = [("clk_sys",100), ("clk_sys_unbuf",100), ("clk200",200)] if args.no_ddr else [
            ("clk",100), ("memory.sys_clk",100), ("memory.sys4x_clk",400),
            ("memory.iodelay_clk",200), ("clk200",200)]
        if args.ddr_cdc:
            clocks = [("clk",args.diagnostic_cpu_mhz), ("dram_clk",dram_mhz), ("memory.sys_clk",dram_mhz),
                      ("memory.cpu_clk",args.diagnostic_cpu_mhz), ("memory.sys4x_clk",4*dram_mhz),
                      ("memory.iodelay_clk",200), ("clk200",200)]
        (build / "clocks.py").write_text("for name, mhz in {!r}:\n    ctx.addClock(name, mhz)\n".format(clocks))
        route_command += ["--pre-pack", build / "clocks.py"]
    if args.seed is not None:
        route_command += ["--seed", args.seed]
    route_command += ["--json", build / "soc.json", "--write", build / "soc_routed.json",
                      "--fasm", build / "soc.fasm"]
    route_env = None
    if args.allow_const_holdouts:
        route_env = dict(os.environ, NEXTPNR_ALLOW_CONST_HOLDOUTS="1")
    run(route_command, "route", env=route_env)
    route_log = (build / "route.log").read_text(errors="replace")
    try:
        validate_route_log(route_log)
    except ValueError as error:
        raise SystemExit("Unsafe route: {}. Do not program its output.".format(error))


if __name__ == "__main__":
    main()
