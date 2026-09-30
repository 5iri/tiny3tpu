#!/usr/bin/env python3
"""Observe GEMM-scoped accelerator activity without changing firmware or RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reference", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--dma-source",type=Path,help="Exact saved backend source when observing an older firmware build")
args = parser.parse_args(); ref = args.reference.resolve(); out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
reference = json.loads((ref / "system/results.json").read_text())
# These generators are not rerun: this observer executes the saved CMake and
# firmware/RTL inputs. Changes to unused driver code do not stale those inputs.
unused_drivers={ROOT/"hardware/synapse32/experiments/dma/run.py",
                ROOT/"hardware/synapse32/experiments/dma/prepare.py",
                ROOT/"tools/synapse32_system_profile.py"}
for name, digest in reference["sha256"].items():
    if Path(name) in unused_drivers: continue
    actual=args.dma_source.resolve() if args.dma_source and Path(name)==ROOT/"src/dma_backend.c" else Path(name)
    assert hashlib.sha256(actual.read_bytes()).hexdigest() == digest, "Stale reference: " + name
workload = reference["metrics"]["workload"]
shapes = reference.get("configuration",{}).get("gemm_shapes")
if shapes is None:
    shapes = {"dram-selftest-gemm-5x11x7-v1": [(5,11,7)],
              "dram-selftest-gemm-five-shapes-v1": [(1,1,1),(4,8,4),(7,13,9),(8,16,8),(3,5,6)]}[workload]
disassembly = subprocess.check_output(["riscv64-unknown-elf-objdump", "-d", "--disassemble=tiny3tpu_dma_qgemm", str(ref / "system/smoke.elf")], text=True)
entry = int(re.search(r"([0-9a-f]+) <tiny3tpu_dma_qgemm>:", disassembly)[1],16)
returns = [int(m[1],16) for m in re.finditer(r"^\s*([0-9a-f]+):\s+00008067\s+ret\s*$",disassembly,re.M)]
assert returns, "Need explicit RV32IM return sites to delimit GEMM calls"
prefix = "root.synapse32_dram_soc__DOT__accelerator__DOT__transport__DOT__accelerator__DOT__"
top = prefix + "u_top__DOT__"
core_states = [top + f"GEN_BIG_CORES__BRA__{i}__KET____DOT__u_core__DOT__state" for i in range(2)]
fields = {
    "launches": f"{prefix}top_start && !{prefix}top_busy && {top}state==0",
    "top_busy_cycles": prefix + "top_busy",
    "local_load_cycles": f"{top}state==1 || {top}state==2",
    "core_busy_cycles_sum": " + ".join(f"unsigned({s}>=1 && {s}<=4)" for s in core_states),
    "core_feed_cycles_sum": " + ".join(f"unsigned({s}==2)" for s in core_states),
    "dma_busy_cycles": "root.synapse32_dram_soc__DOT__dma_busy",
    "dma_only_cycles": f"root.synapse32_dram_soc__DOT__dma_busy && !{prefix}top_busy",
    "tpu_only_cycles": f"!root.synapse32_dram_soc__DOT__dma_busy && {prefix}top_busy",
    "both_busy_cycles": f"root.synapse32_dram_soc__DOT__dma_busy && {prefix}top_busy",
    "neither_busy_cycles": f"!root.synapse32_dram_soc__DOT__dma_busy && !{prefix}top_busy",
    "dma_read_beats": "dut.m_axi_rvalid && dut.m_axi_rready",
    "dma_write_beats": "dut.m_axi_wvalid && dut.m_axi_wready",
    "dma_read_backpressure_cycles": "dut.m_axi_rvalid && !dut.m_axi_rready",
    "dma_write_backpressure_cycles": "dut.m_axi_wvalid && !dut.m_axi_wready",
    "cpu_external_read_requests": "dut.ext_req_valid && dut.ext_req_ready && !dut.ext_req_write",
    "cpu_external_write_requests": "dut.ext_req_valid && dut.ext_req_ready && dut.ext_req_write",
    "cpu_external_pending_cycles": "pending",
}
# These states form a separate exclusive partition of system cycles. They
# overlap DMA/TPU activity; neither partition is added to the other.
seq = "root.synapse32_dram_soc__DOT__sequencer__DOT__"
state_names = ["boot_wait", "fetch_request", "fetch_wait", "step_edge", "settle", "data_request", "data_wait", "fault"]
seq_source = ref / "synapse32_memory_sequencer.sv"
if not seq_source.exists(): seq_source = ROOT / "hardware/synapse32/synapse32_memory_sequencer.sv"
enum_body = re.search(r"typedef enum logic \[3:0\]\s*\{(.*?)\}", seq_source.read_text(), re.S)[1]
assert re.findall(r"ST_[A-Z_]+", enum_body) == ["ST_BOOT_WAIT", "ST_FETCH_REQ", "ST_FETCH_WAIT", "ST_STEP_EDGE", "ST_SETTLE", "ST_DATA_REQ", "ST_DATA_WAIT", "ST_FAULT"]
for index, name in enumerate(state_names):
    fields["seq_" + name + "_cycles"] = f"{seq}state=={index}"
external = f"({seq}request_addr>=0x40000000U && {seq}request_addr<0x80000000U)"
fields["seq_external_data_wait_cycles"] = f"{seq}state==6 && {external}"
fields["seq_local_data_wait_cycles"] = f"{seq}state==6 && !{external}"
fields["seq_dma_status_access_cycles"] = f"({seq}state==5 || {seq}state==6) && {seq}request_addr==0x20003010U && !{seq}request_write"
cpp = (ref / "system/profile.cpp").read_text()
marker = "    uint64_t trace_hash="
declarations = f"    std::array<uint64_t,{len(fields)}> util_total{{}}, util_begin{{}};\n    bool in_gemm=false;\n    unsigned gemm_begin=0, gemm_calls=0;\n    uint64_t gemm_cpu_begin=0, gemm_insn_begin=0;\n"
assert marker in cpp; cpp = cpp.replace(marker, declarations + marker,1)
marker = "        axi_memory.capture(dut);"
count = "        if(!dut.rst) {\n"
count += "\n".join(f"            util_total[{i}] += ({expression});" for i,expression in enumerate(fields.values()))
count += "\n        }\n"
assert marker in cpp; cpp = cpp.replace(marker,count + marker,1)
marker = "                    ++instructions; ++sample[0]; ++instruction_mix[ex_id];"
window = f'''                    if(ex_pc==0x{entry:08x}U) {{
                        if(in_gemm) return 90;
                        in_gemm=true; gemm_begin=cycle; util_begin=util_total;
                        gemm_cpu_begin=cpu_edges; gemm_insn_begin=instructions;
                    }}
                    if(in_gemm && ({' || '.join(f'ex_pc==0x{pc:08x}U' for pc in returns)})) {{
                        std::cout<<"UTIL {{\\"call\\":"<<gemm_calls++<<",\\"system_cycles\\":"<<(cycle-gemm_begin);
                        std::cout<<",\\"cpu_enabled_edges\\":"<<(cpu_edges-gemm_cpu_begin)<<",\\"cpu_instructions\\":"<<(instructions-gemm_insn_begin);
'''
window += "\n".join(f'                        std::cout<<",\\"{name}\\":"<<(util_total[{i}]-util_begin[{i}]);' for i,name in enumerate(fields))
window += '''
                        std::cout<<"}\\n";
                        in_gemm=false;
                    }
'''
assert marker in cpp; cpp = cpp.replace(marker,marker + "\n" + window,1)
(out / "utilization.cpp").write_text(cpp)
cmake = (ref / "system/run.cmake").read_text().replace(str(ref / "system/profile.cpp"),str(out / "utilization.cpp"))
if args.dma_source:
    cmake=cmake.replace('${SOURCE_DIR}/src/dma_backend.c',str(args.dma_source.resolve()))
(out / "run.cmake").write_text(cmake)
command = ["-DBINARY_DIR=" + str(out) if a.startswith("-DBINARY_DIR=") else str(out / "run.cmake") if a==str(ref / "system/run.cmake") else a for a in reference["command"]]
with (out / "run.log").open("w") as log:
    subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
lines = [line.removeprefix("-- ") for line in (out / "run.log").read_text().splitlines()]
jobs = [json.loads(line[5:]) for line in lines if line.startswith("UTIL ")]
assert len(jobs)==len(shapes), "GEMM entry/return window count mismatch"
for key in ("PROFILE","METRICS","DMA"):
    measured = json.loads(next(line[len(key)+1:] for line in lines if line.startswith(key + " ")))
    expected = dict(reference[key.lower()]); expected.pop("cpu_ipc",None)
    assert measured==expected, "Instrumentation changed " + key
assert (out / "smoke.bin").read_bytes()==(ref / "system/smoke.bin").read_bytes()
for job, (m,k,n) in zip(jobs,shapes):
    assert sum(job["seq_"+name+"_cycles"] for name in state_names)==job["system_cycles"]
    assert job["seq_external_data_wait_cycles"]+job["seq_local_data_wait_cycles"]==job["seq_data_wait_cycles"]
    assert job["launches"]==((m+3)//4)*((n+3)//4)*((k+7)//8)
    assert job["local_load_cycles"]==64*job["launches"]
    assert sum(job[p] for p in ("dma_only_cycles","tpu_only_cycles","both_busy_cycles","neither_busy_cycles"))==job["system_cycles"]
    job["shape_mkn"] = [m,k,n]
    job["cpu_enabled_ipc"] = job["cpu_instructions"]/job["cpu_enabled_edges"]
    job["required_useful_macs"] = m*k*n
    job["scheduled_tile_macs"] = 128*job["launches"]
    job["useful_pe_capacity_fraction"] = m*k*n/(32*job["system_cycles"])
    job["scheduled_pe_capacity_fraction"] = job["scheduled_tile_macs"]/(32*job["system_cycles"])
    job["core_active_useful_pe_capacity_fraction"] = m*k*n/(16*job["core_busy_cycles_sum"])
    job["core_busy_fraction"] = job["core_busy_cycles_sum"]/(2*job["system_cycles"])
    job["scheduled_mac_fraction_during_core_busy"] = job["scheduled_tile_macs"]/(16*job["core_busy_cycles_sum"])
    job["padding_efficiency"] = m*k*n/job["scheduled_tile_macs"]
total_instructions=sum(job["cpu_instructions"] for job in jobs)
total_edges=sum(job["cpu_enabled_edges"] for job in jobs)
total_cycles=sum(job["system_cycles"] for job in jobs)
aggregate={"calls":len(jobs),"cpu_instructions":total_instructions,
           "cpu_enabled_edges":total_edges,"system_cycles":total_cycles,
           "sequencer_partition":{name:sum(job["seq_"+name+"_cycles"] for job in jobs) for name in state_names},
           "external_data_wait_cycles":sum(job["seq_external_data_wait_cycles"] for job in jobs),
           "local_data_wait_cycles":sum(job["seq_local_data_wait_cycles"] for job in jobs),
           "dma_status_access_cycles":sum(job["seq_dma_status_access_cycles"] for job in jobs),
           "pooled_cpu_ipc":total_instructions/total_edges,
           "equal_shape_mean_ipc":sum(job["cpu_enabled_ipc"] for job in jobs)/len(jobs),
           "min_shape_ipc":min(job["cpu_enabled_ipc"] for job in jobs),
           "max_shape_ipc":max(job["cpu_enabled_ipc"] for job in jobs),
           "useful_pe_capacity_fraction":sum(job["required_useful_macs"] for job in jobs)/(32*total_cycles),
           "core_active_useful_pe_capacity_fraction":sum(job["required_useful_macs"] for job in jobs)/(16*sum(job["core_busy_cycles_sum"] for job in jobs))}
result = {"reference":str(ref),"jobs":jobs,"aggregate":aggregate,"unchanged_firmware_and_profiles":True,
          "measurement":"GEMM entry instruction completion to return instruction completion, excluding boot/selftest and caller verification",
          "mac_numerator":"Required useful MACs = m*k*n; scheduled MACs = accepted launches*2*4^3, derived from the fixed tile schedule, not nonzero operands or raw PE updates",
          "denominator":"32 PE slots per system clock; each core-busy cycle contributes 16 PE slots",
          "limitations":"Behavioral CPU/DMA memory model; not physical DDR bandwidth/contention. Busy and backpressure are observations, not attribution of idle cycles to DDR starvation.",
          "command":command}
paths = [Path(__file__),out / "utilization.cpp",out / "run.cmake",out / "smoke.bin",ref / "system/results.json",
         args.dma_source.resolve() if args.dma_source else ROOT/"src/dma_backend.c"]
result["sha256"] = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
(out / "results.json").write_text(json.dumps(result,indent=2) + "\n")
print(json.dumps(jobs,indent=2))
