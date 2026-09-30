#!/usr/bin/env python3
"""Build and simulate the generated banana fixture on the real no-DDR CPU/TPU RTL."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "build-banana/render")
    parser.add_argument("--synapse32-dir", type=Path, default=ROOT.parent / "synapse32")
    parser.add_argument("--out", type=Path, default=ROOT / "build-cloth/rtl")
    parser.add_argument("--live", action="store_true", help="Validate the full UART live protocol")
    parser.add_argument("--vertices", type=Path, default=ROOT / "build-cloth")
    args = parser.parse_args()
    out, fixture, uart = args.out.resolve(), args.fixture.resolve(), args.synapse32_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    def run(command, name):
        with (out / f"{name}.log").open("w") as log:
            completed = subprocess.run([str(v) for v in command], stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode:
            raise RuntimeError(f"{name} exited {completed.returncode}: " + (out / f"{name}.log").read_text()[-8000:])

    fw = ROOT / "hardware/synapse32"
    sidequest = ROOT / "sidequests/cloth"
    run(["riscv64-unknown-elf-gcc", "-march=rv32im_zicsr_zifencei", "-mabi=ilp32", "-Os",
         "-ffreestanding", "-fno-builtin", "-nostdlib", "-msmall-data-limit=0",
         "-ffunction-sections", "-fdata-sections", "-Wall", "-Wextra", "-Werror",
         "-I" + str(ROOT / "include"), "-I" + str(fixture), "-I" + str(args.vertices.resolve()),
         "-Wl,--no-relax,--gc-sections", "-T" + str(fw / "bringup.ld"),
         fw / "start.S", sidequest / ("transform_firmware.c" if args.live else "firmware.c"),
         ROOT / "src/mmio_backend.c", ROOT / "src/axis_mailbox.c",
         "-lgcc", "-o", out / "firmware.elf"], "firmware")
    run(["riscv64-unknown-elf-objcopy", "-O", "verilog", "--verilog-data-width=4",
         "--change-addresses=-0x80000000", out / "firmware.elf", out / "firmware.hex"], "image")
    rtl = [ROOT / "hardware/kc705_vexriscv/vexriscv_tpu_soc.sv",
           ROOT / "third_party/vexriscv/VexRiscv_Lite.v", uart / "rtl/core_modules/uart.v"]
    rtl += [ROOT / "multi-core" / name for name in (
        "synapse32_tpu_peripheral.sv", "synapse32_axis_mailbox.sv", "tiny3tpu_axis.sv",
        "tiny3tpu_axis_bridge.sv", "tiny3tpu_axi.sv", "top.v", "tpu_core_wrapper.sv")]
    rtl += [ROOT / "systolic_array/rtl" / name for name in ("NxN_systolic_array.v", "pe.v")]
    run(["verilator", "--cc", "--exe", "--build", "-j", "2", "-Wno-fatal",
         "--top-module", "vexriscv_tpu_soc", "--Mdir", out / "obj",
         f'-GBOOT_HEX="{out / "firmware.hex"}"', "-I" + str(uart / "rtl/include"),
         "-CFLAGS", "-I" + str(fixture) + " -I" + str(args.vertices.resolve())] + rtl +
        [sidequest / ("transforms_uart_sim.cpp" if args.live else "firmware_sim.cpp")], "compile")
    run([out / "obj/Vvexriscv_tpu_soc"], "run")
    print((out / "run.log").read_text(), end="")


if __name__ == "__main__":
    main()
