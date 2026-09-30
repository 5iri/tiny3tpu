#!/usr/bin/env python3
"""Profile the actual CPU + memory model + TPU, without instrumenting firmware.

The EX completion counter is used only for this no-interrupt/no-fault workload.
CPU IPC counts enabled CPU edges. Function cycle attribution is EX-stage PC
residency, not call-inclusive time. Firmware variants may execute different
instruction streams; correctness and application work must be compared too.
"""
import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cpu-overlay-dir", type=Path, required=True)
    parser.add_argument("--isa", choices=("rv32i", "rv32im"), default="rv32i")
    parser.add_argument("--prepare-only", action="store_true", help="Materialize the observational harness for an integration experiment")
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    overlay = args.cpu_overlay_dir.resolve()
    source = ROOT.parent / "synapse32"
    original = ROOT / "tests/synapse32_dram_test.cpp"
    cpp = original.read_text().replace('#include <cstdint>', '#include <cstdint>\n#include <array>\n#include "Vsynapse32_dram_soc___024root.h"')
    cpp = cpp.replace('    unsigned reads=0', '''    std::unordered_map<uint32_t,std::array<uint64_t,3>> pc_profile;
    std::array<uint64_t,128> instruction_mix{};
    uint64_t cpu_edges=0, instructions=0, hazard_edges=0, divider_edges=0;
    uint64_t trace_hash=14695981039346656037ULL;
    auto& root=*dut.rootp;
    unsigned reads=0''')
    cpp = cpp.replace('        dut.clk=1; dut.eval();', '''        const auto ex_pc=root.synapse32_dram_soc__DOT__cpu__DOT__id_ex_inst0_pc_out;
        const auto ex_id=root.synapse32_dram_soc__DOT__cpu__DOT__id_ex_inst0_instr_id_out;
        const auto valid=root.synapse32_dram_soc__DOT__cpu__DOT__id_ex_inst0_instr_valid_out;
        const auto before=root.synapse32_dram_soc__DOT__cpu__DOT__csr_file_inst__DOT__instret_counter;
        const bool hazard=root.synapse32_dram_soc__DOT__cpu__DOT__hazard_stall;
        const bool dividing=root.synapse32_dram_soc__DOT__cpu__DOT__div_wait;
        const bool exceptional=root.synapse32_dram_soc__DOT__cpu__DOT__interrupt_taken_qualified ||
                               root.synapse32_dram_soc__DOT__cpu__DOT__synchronous_exception_taken;
        dut.clk=1; dut.eval();
        if (!dut.rst) {
            auto& sample=pc_profile[valid ? ex_pc : 0];
            ++sample[2];
            if (root.synapse32_dram_soc__DOT__cpu_clk) {
                if (exceptional) { std::cerr<<"Profiling requires no exceptions\\n"; return 98; }
                ++cpu_edges; ++sample[1]; hazard_edges+=hazard; divider_edges+=dividing;
                const auto after=root.synapse32_dram_soc__DOT__cpu__DOT__csr_file_inst__DOT__instret_counter;
                if (after!=before) {
                    if (!valid || after!=before+1) return 99;
                    ++instructions; ++sample[0]; ++instruction_mix[ex_id];
                    trace_hash=(trace_hash ^ ex_pc)*1099511628211ULL;
                    trace_hash=(trace_hash ^ ex_id)*1099511628211ULL;
                }
            }
        }''')
    cpp = cpp.replace('            return 0;', '''            std::cout<<"PROFILE {\\"cpu_edges\\":"<<cpu_edges<<",\\"instructions\\":"<<instructions
                     <<",\\"hazard_edges\\":"<<hazard_edges<<",\\"divider_edges\\":"<<divider_edges
                     <<",\\"trace_hash_fnv64\\":"<<trace_hash<<",\\"pc\\":[";
            bool first=true;
            for (const auto& item:pc_profile) {
                if (!first) std::cout<<',';
                first=false;
                std::cout<<'['<<item.first<<','<<item.second[0]<<','<<item.second[1]<<','<<item.second[2]<<']';
            }
            std::cout<<"],\\"instruction_mix\\":[";
            for (unsigned i=0;i<128;++i) { if(i) std::cout<<','; std::cout<<instruction_mix[i]; }
            std::cout<<"]}\\n";
            return 0;''')
    (out / "profile.cpp").write_text(cpp)
    cmake_original = ROOT / "tests/run_synapse32_cpu_test.cmake"
    cmake = cmake_original.read_text().replace('${SOURCE_DIR}/tests/synapse32_dram_test.cpp', str(out / "profile.cpp"))
    cmake = cmake.replace('-march=rv32i_zicsr_zifencei', '-march=' + args.isa + '_zicsr_zifencei')
    (out / "run.cmake").write_text(cmake)
    command = ["cmake", "-DSOURCE_DIR=" + str(ROOT), "-DBINARY_DIR=" + str(out),
               "-DSYNAPSE32_DIR=" + str(source), "-DCPU_OVERLAY_DIR=" + str(overlay),
               "-DVERILATOR=verilator", "-DRISCV_GCC=riscv64-unknown-elf-gcc",
               "-DRISCV_OBJCOPY=riscv64-unknown-elf-objcopy", "-DDRAM_TEST=ON", "-P", str(out / "run.cmake")]
    if args.prepare_only:
        return
    with (out / "run.log").open("w") as log:
        rc = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
    if rc:
        print((out / "run.log").read_text()[-6000:]); raise SystemExit(rc)
    log = (out / "run.log").read_text().splitlines()
    profile = json.loads(next(line.removeprefix("PROFILE ") for line in log if line.startswith("PROFILE ")))
    profile["metrics"] = json.loads(next(line.removeprefix("METRICS ") for line in log if line.startswith("METRICS ")))
    profile["cpu_ipc"] = profile["instructions"] / profile["cpu_edges"]
    nm = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", "--defined-only", str(out / "smoke.elf")], text=True)
    (out / "symbols.txt").write_text(nm)
    symbols = [(int(words[0], 16), words[2]) for line in nm.splitlines()
               if len(words := line.split()) == 3 and words[1] in ("t", "T")]
    addresses = [address for address, name in symbols]
    functions = {}
    for pc, insns, edges, system in profile["pc"]:
        symbol = bisect_right(addresses, pc) - 1
        name = symbols[symbol][1] if symbol >= 0 else "<bubble>"
        sample = functions.setdefault(name, {"instructions": 0, "cpu_edges_at_pc": 0, "system_cycles_at_pc": 0})
        sample["instructions"] += insns; sample["cpu_edges_at_pc"] += edges; sample["system_cycles_at_pc"] += system
    profile["functions"] = functions
    profile["isa"] = args.isa
    profile["command"] = command
    paths = [Path(__file__), original, cmake_original, out / "profile.cpp", out / "run.cmake", out / "smoke.elf", out / "smoke.bin"]
    paths += sorted(overlay.glob("*.v"))
    paths += [ROOT / p for p in ("hardware/synapse32/stream_smoke.c", "hardware/synapse32/dram_selftest.c", "src/axis_mailbox.c", "src/mmio_backend.c")]
    profile["sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    print(f"PASS {args.isa}: {profile['instructions']} instructions / {profile['cpu_edges']} CPU edges = {profile['cpu_ipc']:.6f} IPC; {profile['metrics']['system_cycles']} system cycles")
    for name, sample in sorted(functions.items(), key=lambda item: -item[1]["instructions"])[:12]:
        print(name, sample)


if __name__ == "__main__":
    main()
