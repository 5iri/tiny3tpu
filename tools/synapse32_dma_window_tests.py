#!/usr/bin/env python3
"""Test DMA command-window bounds and error propagation with actual RV32IM firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reference", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--capacity", type=int, default=256)
parser.add_argument("--a-offset", type=int, choices=range(4), default=0)
parser.add_argument("--b-offset", type=int, choices=range(4), default=0)
parser.add_argument("--extreme-inputs", action="store_true")
parser.add_argument("--fault", choices=("none", "read", "write"), default="none")
args = parser.parse_args()
assert args.capacity in (96, 112, 113, 256)
ref, out = args.reference.resolve(), args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
reference = json.loads((ref / "system/results.json").read_text())
for name, digest in reference["sha256"].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, "Stale reference: " + name
firmware = (ref / "stream_smoke.c").read_text()
assert firmware.count(", 256, 100000, 0}") == 1
firmware = firmware.replace(", 256, 100000, 0}", f", {args.capacity}, 100000, 0}}")
calls = [line for line in firmware.splitlines() if "if (tiny3tpu_dma_qgemm(" in line]
assert len(calls) == 1
call = calls[0]
checks = '''        if (dma.commands[2*dma.capacity]!=0x13579bdfU ||
            dma.responses[2*dma.capacity]!=0x2468ace0U) return 24;
        if ((uintptr_t)dma.commands!=0x40020000U || (uintptr_t)dma.responses!=0x40022000U) return 25;
'''
prefix = '''        dma.commands[2*dma.capacity]=0x13579bdfU;
        dma.responses[2*dma.capacity]=0x2468ace0U;
'''
cpp = (ref / "system/profile.cpp").read_text()
if args.a_offset or args.b_offset:
    assert reference["metrics"]["workload"].startswith("dram-selftest-gemm-sweep-")
    for address, offset in ((0x40010000,args.a_offset),(0x40011000,args.b_offset)):
        old=f"UINT32_C(0x{address:08x})"
        assert firmware.count(old)==1
        firmware=firmware.replace(old,f"UINT32_C(0x{address+offset:08x})")
if args.extreme_inputs:
    assert "(i%17)-8" in firmware and "(i%13)-6" in firmware
    firmware=firmware.replace("(i%17)-8","(i%256)-128").replace("(i%13)-6","(i%256)-128")
    assert "%17)-8" in cpp and "%13)-6" in cpp
    cpp=cpp.replace("%17)-8","%256)-128").replace("%13)-6","%256)-128")

if args.fault != "none":
    assert reference["metrics"]["workload"] == "dram-selftest-gemm-5x11x7-v1" and args.capacity >= 113
    # The injected failure is on the cached result descriptor, not a load.
    failure = call.replace(") return 4;", "!=-1 || dma.poisoned!=1) return 26;")
    prefix += failure + "\n" + checks + '''        if (dma.registers[4]!=0 || tiny3tpu_dma_init(&dma)) return 27;
'''
    cpp = cpp.replace("    AxiDmaMemory axi_memory(memory);", "    AxiDmaMemory axi_memory(memory);\n    bool inject_armed=true, inject_active=false;")
    channel, address = ("ar", "0x40020088U") if args.fault == "read" else ("aw", "0x40022088U")
    trigger = f"        if(inject_armed && dut.m_axi_{channel}valid && dut.m_axi_{channel}addr=={address}) inject_active=true;\n        axi_memory.{args.fault}_error=inject_active;\n"
    cpp = cpp.replace("        axi_memory.drive(dut);", trigger + "        axi_memory.drive(dut);")
    accepted = "dut.m_axi_rvalid && dut.m_axi_rready && dut.m_axi_rlast" if args.fault == "read" else "dut.m_axi_bvalid && dut.m_axi_bready"
    cpp = cpp.replace("        axi_memory.capture(dut);", f"        axi_memory.capture(dut);\n        if(inject_active && ({accepted})) {{ inject_active=false; inject_armed=false; }}")
    cpp = cpp.replace('            std::cout<<"PROFILE ', '            if(inject_armed) return 28;\n            std::cout<<"PROFILE ')
firmware = firmware.replace(call, prefix + call + "\n" + checks)
(out / "firmware.c").write_text(firmware)
(out / "profile.cpp").write_text(cpp)
cmake = (ref / "system/run.cmake").read_text().replace(str(ref / "stream_smoke.c"), str(out / "firmware.c"))
cmake = cmake.replace(str(ref / "system/profile.cpp"), str(out / "profile.cpp"))
(out / "run.cmake").write_text(cmake)
command = ["-DBINARY_DIR=" + str(out) if a.startswith("-DBINARY_DIR=") else str(out / "run.cmake") if a == str(ref / "system/run.cmake") else a for a in reference["command"]]
with (out / "run.log").open("w") as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
result = {"passed": True, "capacity": args.capacity, "fault": args.fault,"input_offsets":[args.a_offset,args.b_offset],"extreme_inputs":args.extreme_inputs,
          "checks": "Buffer-end canaries, unchanged caller buffer pointers, original GEMM scoreboard; injected faults also check parent poisoning, acknowledgment and reinitialization",
          "command": command}
paths = [Path(__file__), out / "firmware.c", out / "profile.cpp", out / "run.cmake", out / "smoke.bin", ref / "system/results.json"]
result["sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
(out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
print(f"PASS RV32IM DMA windows: capacity={args.capacity}, fault={args.fault}")
