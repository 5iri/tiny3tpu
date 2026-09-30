#!/usr/bin/env python3
"""Isolated, registered-boundary KC705 timing probes; never programs hardware.

The scan shell preserves arbitrary core inputs/outputs using board-compatible
pins. It is not a functional SoC, memory controller, or a CPU migration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_COMMIT = "642ecfed1c84460555d6d803d660cc60cfc1ecb6"
YOSYS = Path.home() / ".apio/packages/oss-cad-suite/bin/yosys"
NEXTPNR = Path.home() / ".apio/packages/openxc7/libexec/nextpnr-xilinx"
CHIPDB = Path("/tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", choices=["vex-min", "vex-lite", "tpu"])
    args = parser.parse_args()
    out = ROOT / "build-cpu-comparison" / args.probe
    out.mkdir(parents=True, exist_ok=True)
    upstream = ROOT / "build-cpu-comparison/upstream"
    if args.probe.startswith("vex"):
        commit = subprocess.check_output(["git", "-C", upstream, "rev-parse", "HEAD"], text=True).strip()
        if commit != UPSTREAM_COMMIT:
            raise SystemExit("Unexpected VexRiscv source revision")
        variant = "Min" if args.probe == "vex-min" else "Lite"
        sources = [upstream / f"pythondata_cpu_vexriscv/verilog/VexRiscv_{variant}.v"]
        header = sources[0].read_text().split(");", 1)[0]
        ports = []
        for direction, width, name in re.findall(r"\b(input|output)\s+(?:wire|reg)\s+(\[\d+:0\])?\s*(\w+)", header):
            ports.append((direction, name, int(width[1:].split(":")[0]) + 1 if width else 1))
        module = "VexRiscv"
        fixed = {"clk": "clk", "reset": "rst", "externalResetVector": "32'h80000000",
                 "timerInterrupt": "1'b0", "softwareInterrupt": "1'b0", "externalInterruptArray": "32'b0"}
    else:
        sources = [ROOT / "multi-core" / name for name in (
            "synapse32_tpu_peripheral.sv", "synapse32_axis_mailbox.sv", "tiny3tpu_axis.sv",
            "tiny3tpu_axis_bridge.sv", "tiny3tpu_axi.sv", "top.v", "tpu_core_wrapper.sv")]
        sources += [ROOT / "systolic_array/rtl" / name for name in ("NxN_systolic_array.v", "pe.v")]
        ports = [("input", "clk", 1), ("input", "rst_n", 1), ("input", "cpu_wr_en", 1),
                 ("input", "cpu_rd_en", 1), ("input", "cpu_addr", 5), ("input", "cpu_wdata", 32),
                 ("input", "cpu_wstrb", 4), ("output", "cpu_rdata", 32)]
        module = "synapse32_tpu_peripheral"
        fixed = {"clk": "clk", "rst_n": "!rst"}
    inputs = sum(w for d, n, w in ports if d == "input" and n not in fixed)
    outputs = sum(w for d, n, w in ports if d == "output")
    connections = []
    cursor = {"input": 0, "output": 0}
    for direction, name, width in ports:
        if name in fixed:
            value = fixed[name]
        else:
            offset = cursor[direction]
            value = f'{"stimulus" if direction == "input" else "core_outputs"}[{offset} +: {width}]'
            cursor[direction] += width
        connections.append(f".{name}({value})")
    wrapper = f"""module timing_probe(
    input wire clk_p, clk_n, reset_btn, uart_rx,
    output wire uart_tx, output wire [7:0] led
);
    wire clk200, clk_unbuf, clk, pll_fb, locked;
    IBUFDS #(.IOSTANDARD("LVDS")) oscillator(.I(clk_p), .IB(clk_n), .O(clk200));
    PLLE2_ADV #(.CLKFBOUT_MULT(5), .CLKIN1_PERIOD(5.0), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(10), .CLKOUT0_DUTY_CYCLE(0.5), .CLKOUT0_PHASE(0.0)) pll (
        .CLKIN1(clk200), .CLKIN2(1'b0), .CLKINSEL(1'b1), .CLKFBIN(pll_fb),
        .CLKFBOUT(pll_fb), .CLKOUT0(clk_unbuf), .LOCKED(locked), .RST(1'b0),
        .PWRDWN(1'b0), .DADDR(7'b0), .DCLK(1'b0), .DEN(1'b0), .DI(16'b0), .DWE(1'b0));
    BUFG system_clock(.I(clk_unbuf), .O(clk));
    reg [1:0] reset_sync = 2'b11;
    always @(posedge clk) reset_sync <= {{reset_sync[0], !locked}};
    wire rst = reset_sync[1];
    reg [{inputs-1}:0] stimulus = 0;
    wire [{outputs-1}:0] core_outputs;
    reg [{outputs-1}:0] observation = 0;
    always @(posedge clk) begin
        stimulus <= {{stimulus[{inputs-2}:0], uart_rx}};
        if (reset_btn) observation <= {{observation[{outputs-2}:0], 1'b0}};
        else observation <= core_outputs;
    end
    assign uart_tx = observation[{outputs-1}];
    assign led = {{observation[6:0], locked}};
    {module} core({', '.join(connections)});
endmodule
"""
    (out / "timing_probe.v").write_text(wrapper)
    # Same clock pin and board IO assignment as the actual no-DDR SoC.
    xdc = ROOT / "build-clock-diagnosis/noddr/kc705.xdc"
    if not xdc.exists():
        raise SystemExit("Generate the no-DDR KC705 XDC with kc705_open_build.py first")
    (out / "kc705.xdc").write_text(xdc.read_text())
    (out / "clocks.py").write_text('for name, mhz in [("clk",100),("clk_unbuf",100),("clk200",200)]:\n    ctx.addClock(name,mhz)\n')
    sources += [out / "timing_probe.v"]
    script = "read_verilog -sv " + " ".join(str(p) for p in sources) + "\n"
    script += "read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v\n"
    script += "hierarchy -check -top timing_probe\n"
    script += f"synth_xilinx -family xc7 -flatten -top timing_probe -json {out / 'soc.json'}\ncheck -assert\nstat\n"
    (out / "synth.ys").write_text(script)
    commands = [[str(YOSYS), "-Q", "-T", "-s", str(out / "synth.ys")],
                [str(NEXTPNR), "--chipdb", str(CHIPDB), "--xdc", str(out / "kc705.xdc"),
                 "--pre-pack", str(out / "clocks.py"), "--freq", "100", "--seed", "4",
                 "--json", str(out / "soc.json"), "--write", str(out / "soc_routed.json"),
                 "--report", str(out / "report.json"), "--log", str(out / "route.log")]]
    record = {"probe": args.probe, "scope": "Isolated registered-boundary timing probe; not a working SoC or physical signoff", "upstream_commit": UPSTREAM_COMMIT if args.probe.startswith("vex") else None,
              "commands": commands, "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    for command, name in zip(commands, ["synth", "route-console"]):
        print(f"{args.probe}: {name}", flush=True)
        with (out / f"{name}.log").open("w") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise SystemExit(f"{name} failed ({result.returncode}): {out}")
    report = json.loads((out / "report.json").read_text())
    record["fmax"] = report["fmax"]
    record["native_timing_rejected"] = "FAIL at" in (out / "route.log").read_text()
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"probe": args.probe, "fmax": record["fmax"], "native_timing_rejected": record["native_timing_rejected"]}), flush=True)
    if record["native_timing_rejected"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
