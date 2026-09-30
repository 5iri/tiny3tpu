#!/usr/bin/env python3
"""Run real VexRiscv firmware against the TPU and a backpressured RAM model.

The dram mode tests transactions and firmware, not the DDR PHY/calibration.
The noddr mode also decodes the 100 MHz firmware's UART at 115200 baud.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["noddr", "dram", "interconnect", "interconnect-pipelined", "wide", "cdc"])
    p.add_argument("--synapse32-dir", type=Path, required=True, help="UART RTL source checkout")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    uart = a.synapse32_dir.resolve()
    fw = ROOT / "hardware/synapse32"

    def run(cmd, name):
        cmd = list(map(str, cmd))
        (out / (name + "-command.json")).write_text(json.dumps(cmd, indent=2) + "\n")
        with (out / (name + ".log")).open("w") as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        if result.returncode:
            print((out / (name + ".log")).read_text()[-8000:])
            raise SystemExit(result.returncode)

    rtl = [ROOT / "hardware/kc705_vexriscv/vexriscv_tpu_soc.sv", uart / "rtl/core_modules/uart.v"]
    rtl += [ROOT / "multi-core" / name for name in (
        "synapse32_tpu_peripheral.sv", "synapse32_axis_mailbox.sv", "tiny3tpu_axis.sv",
        "tiny3tpu_axis_bridge.sv", "tiny3tpu_axi.sv", "top.v", "tpu_core_wrapper.sv")]
    rtl += [ROOT / "systolic_array/rtl" / name for name in ("NxN_systolic_array.v", "pe.v")]
    if a.mode.startswith("interconnect"):
        run(["iverilog", "-g2012", "-s", "tb", "-Ptb.PIPELINED_DECODE=" + str(int(a.mode.endswith("-pipelined"))),
             "-I" + str(uart / "rtl/include"),
             "-o", out / "test", ROOT / "tests/tb_vexriscv_interconnect.sv",
             ROOT / "tests/vexriscv_bus_master_stub.sv"] + rtl, "compile")
        run(["vvp", out / "test"], "run")
        print((out / "run.log").read_text(), end="")
        return

    sources = [fw / "start.S", ROOT / "src/axis_mailbox.c", ROOT / "src/mmio_backend.c"]
    flags = ["-DCONFIG_CLOCK_FREQUENCY=100000000UL"]
    if a.mode in ("dram", "wide", "cdc"):
        sources += [fw / "stream_smoke.c", fw / "dram_selftest.c"]
        flags += ["-DTINY3TPU_DRAM_SMOKE"]
    else:
        sources += [fw / "noddr_selftest.c"]
    run(["riscv64-unknown-elf-gcc", "-march=rv32im_zicsr_zifencei", "-mabi=ilp32",
         "-Os", "-ffreestanding", "-fno-builtin", "-nostdlib", "-msmall-data-limit=0",
         "-ffunction-sections", "-fdata-sections", "-Wall", "-Wextra", "-Werror",
         "-I" + str(ROOT / "include"), "-I" + str(fw), "-Wl,--no-relax,--gc-sections",
         "-T" + str(fw / "bringup.ld")] + flags + sources + ["-lgcc", "-o", out / "firmware.elf"], "firmware")
    run(["riscv64-unknown-elf-objcopy", "-O", "verilog", "--verilog-data-width=4",
         "--change-addresses=-0x80000000", out / "firmware.elf", out / "firmware.hex"], "image")
    rtl += [ROOT / "third_party/vexriscv/VexRiscv_Lite.v"]
    top = "vexriscv_tpu_soc"
    if a.mode in ("wide", "cdc"):
        top = "vexriscv_ddr_wide_test_top"
        rtl += [ROOT / "tests/vexriscv_ddr_wide_test_top.sv",
                fw / "litedram_wishbone_bridge.sv",
                ROOT / "hardware/kc705_vexriscv/litedram_wishbone32_to512.sv",
                ROOT / "hardware/kc705_vexriscv/req_resp_cdc.sv"]
    extra = ["-GASYNC_DDR=1"] if a.mode == "cdc" else []
    run(["verilator", "--cc", "--exe", "--build", "-j", "2", "-Wno-fatal",
         "--top-module", top, "--Mdir", out / "obj",
         '-GBOOT_HEX="{}"'.format(out / "firmware.hex"), "-I" + str(uart / "rtl/include")]
        + extra + rtl + [ROOT / "tests" / ("vexriscv_" + a.mode + "_test.cpp")], "compile")
    run([out / "obj" / ("V" + top)], "run")
    print((out / "run.log").read_text(), end="")


if __name__ == "__main__":
    main()
