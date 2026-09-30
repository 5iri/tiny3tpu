#!/usr/bin/env python3
"""Account for every enabled CPU edge in an existing no-fault DMA workload."""
import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reference", type=Path, required=True, help="Existing DMA experiment output")
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--dma-source", type=Path, help="Exact saved DMA firmware source for auditing an older build")
args = parser.parse_args(); ref = args.reference.resolve(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
result = json.loads((ref / "system/results.json").read_text())
cpp = (ref / "system/profile.cpp").read_text()
cpp = cpp.replace("    uint64_t trace_hash=", '''    // Tag the two pipeline slots independently of the RTL validity bits.
    // 0=instruction, 1=reset fill, 2=redirect flush, 3=load-use insertion.
    unsigned if_tag=1, ex_tag=1;
    uint32_t if_owner=0, ex_owner=0;
    uint64_t audit_edges=0, audit_retired=0, audit_div=0, audit_redirects=0;
    uint64_t audit_hazards=0;
    std::array<uint64_t,4> bubbles{};
    std::unordered_map<uint32_t,std::array<uint64_t,6>> audit_pc;
    uint64_t trace_hash=''')
cpp = cpp.replace("        axi_memory.capture(dut);", '''        const bool jump=root.synapse32_dram_soc__DOT__cpu__DOT__ex_inst0_jump_signal_out;
        const bool hold=root.synapse32_dram_soc__DOT__cpu__DOT__pipeline_hold;
        const bool if_valid=root.synapse32_dram_soc__DOT__cpu__DOT__if_id_instr_valid_out;
        const auto cycle_before=root.synapse32_dram_soc__DOT__cpu__DOT__csr_file_inst__DOT__cycle_counter;
        axi_memory.capture(dut);''')
marker = "                ++cpu_edges; ++sample[1]; hazard_edges+=hazard; divider_edges+=dividing;"
extra = '''
                ++audit_edges;
                const auto cycle_after=root.synapse32_dram_soc__DOT__cpu__DOT__csr_file_inst__DOT__cycle_counter;
                if(cycle_after!=cycle_before+1 || valid!=(ex_tag==0) || if_valid!=(if_tag==0)) {
                    std::cerr<<"IPC audit clock/validity mismatch\\n";return 97;
                }
                auto& a=audit_pc[valid ? ex_pc : ex_owner]; ++a[1];
                const auto retired_now=root.synapse32_dram_soc__DOT__cpu__DOT__csr_file_inst__DOT__instret_counter!=before;
                if(retired_now) {++audit_retired; ++a[0];}
                else if(!valid) {++bubbles[ex_tag]; ++a[ex_tag+1];}
                else if(dividing) {++audit_div; ++a[5];}
                else {std::cerr<<"Unclassified enabled cycle pc="<<ex_pc<<"\\n";return 96;}
                if(jump) ++audit_redirects;
                if(hazard && !hold && !jump) ++audit_hazards;
                if(jump) {
                    if_tag=2; ex_tag=2; if_owner=ex_pc; ex_owner=ex_pc;
                } else {
                    if(!hold) {
                        if(hazard) {ex_tag=3; ex_owner=ex_pc;}
                        else {ex_tag=if_tag; ex_owner=if_owner;}
                    }
                    if(!hazard && !hold) {if_tag=0; if_owner=0;}
                }
'''
assert marker in cpp
cpp = cpp.replace(marker, marker + extra, 1)
marker = '            std::cout<<"PROFILE '
audit_output = '''            std::cout<<"AUDIT {\\"enabled_edges\\":"<<audit_edges<<",\\"retired\\":"<<audit_retired
                <<",\\"startup_bubbles\\":"<<bubbles[1]<<",\\"redirect_bubbles\\":"<<bubbles[2]
                <<",\\"load_use_bubbles\\":"<<bubbles[3]<<",\\"divider_waits\\":"<<audit_div
                <<",\\"redirects\\":"<<audit_redirects<<",\\"load_use_insertions\\":"<<audit_hazards
                <<",\\"pc\\":[";
            bool audit_first=true;
            for(const auto& [pc,a]:audit_pc) {
                if(!audit_first) std::cout<<',';audit_first=false;
                std::cout<<'['<<pc;for(auto v:a)std::cout<<','<<v;std::cout<<']';
            }
            std::cout<<"]}\\n";
'''
assert marker in cpp
cpp = cpp.replace(marker, audit_output + marker, 1)
(out / "audit.cpp").write_text(cpp)
cmake = (ref / "system/run.cmake").read_text().replace(str(ref / "system/profile.cpp"), str(out / "audit.cpp"))
dma_source = args.dma_source.resolve() if args.dma_source else ROOT / "src/dma_backend.c"
assert hashlib.sha256(dma_source.read_bytes()).hexdigest() == result["sha256"][str(ROOT / "src/dma_backend.c")], "Choose the exact DMA source recorded in the reference build"
cmake = cmake.replace('${SOURCE_DIR}/src/dma_backend.c', str(dma_source))
(out / "run.cmake").write_text(cmake)
command = [str(x) for x in result["command"]]
command = ["-DBINARY_DIR=" + str(out) if a.startswith("-DBINARY_DIR=") else str(out / "run.cmake") if a == str(ref / "system/run.cmake") else a for a in command]
with (out / "run.log").open("w") as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
lines = (out / "run.log").read_text().splitlines()
audit = json.loads(next(line[6:] for line in lines if line.startswith("AUDIT ")))
profile = json.loads(next(line[8:] for line in lines if line.startswith("PROFILE ")))
assert audit["enabled_edges"] == result["profile"]["cpu_edges"] == profile["cpu_edges"]
assert audit["retired"] == result["profile"]["instructions"] == profile["instructions"]
assert audit["enabled_edges"] == sum(audit[k] for k in ("retired","startup_bubbles","redirect_bubbles","load_use_bubbles","divider_waits"))
assert (out / "smoke.bin").read_bytes() == (ref / "system/smoke.bin").read_bytes()
nm = subprocess.check_output(["riscv64-unknown-elf-nm","-n","--defined-only",str(out / "smoke.elf")], text=True)
symbols = [(int(w[0],16),w[2]) for line in nm.splitlines() if len(w:=line.split())==3 and w[1] in ("t","T")]
addresses = [a for a,n in symbols]; functions = {}
fields = ("instructions","cpu_edges","startup_bubbles","redirect_bubbles","load_use_bubbles","divider_waits")
for pc,*values in audit["pc"]:
    index = bisect_right(addresses,pc)-1
    name = symbols[index][1] if index>=0 else "<startup>"
    stats = functions.setdefault(name,dict.fromkeys(fields,0))
    for field,value in zip(fields,values): stats[field]+=value
for stats in functions.values(): stats["ipc"] = stats["instructions"]/stats["cpu_edges"]
audit["functions"] = functions; audit["ipc"] = audit["retired"]/audit["enabled_edges"]
audit["reference"] = str(ref); audit["command"] = command
paths = [Path(__file__),out / "audit.cpp",out / "run.cmake",out / "smoke.bin",ref / "system/results.json",dma_source]
audit["sha256"] = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
(out / "results.json").write_text(json.dumps(audit,indent=2)+"\n")
print(json.dumps({k:v for k,v in audit.items() if k not in ("pc","command","sha256")},indent=2))
