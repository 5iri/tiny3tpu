#!/usr/bin/env python3
"""Compare identical MUL-heavy programs without latency-dependent IRQ stimulus.

Checks identical instruction-completion traces, stores and MUL writebacks.
Reports instructions per enabled CPU edge and per system cycle separately.
The CPU's instret signal resolves instructions in EX; this benchmark disables
interrupts and faults and drains the pipeline. It is not a precise retirement
test for exceptions, or a hardware performance measurement.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
from prepare import benches,ROOT

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out",type=Path,required=True)
parser.add_argument("--baseline",type=Path,default=ROOT/"build-ddr-retime")
parser.add_argument("--candidate",type=Path,default=ROOT/"build-ddr-mul")
parser.add_argument("--candidate-system-mul",action="store_true",
                    help="Enable the candidate's system-clock MUL only in gated mode")
args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
benches(out)
tb=(out/"cpu_mul_tb.sv").read_text().replace("module cpu_mul_tb;","module cpu_m_workload_tb;")
tb=tb.replace("    reg clk=0, rst=1;", """    integer trace_fd;
    string trace_path;
    initial begin
        if (!$value$plusargs("trace=%s", trace_path)) $fatal(1,"missing trace path");
        trace_fd=$fopen(trace_path,"w");
        if (!trace_fd) $fatal(1,"cannot open trace");
    end
    reg clk=0, rst=1;""")
start=tb.index("    always @(posedge cpu_clk)")
end=tb.index("    initial begin",start)
tb=tb[:start]+"""    always @(posedge cpu_clk) begin
        if(rst) begin seen=0;edges=0;written=0;data_reads=0;retired=0;end
        else begin
            edges=edges+1;
            if(cpu.interrupt_taken_qualified || cpu.synchronous_exception_taken ||
               cpu.mem_stage_page_fault_taken || cpu.instr_stage_page_fault_taken)
                $fatal(1,"IPC benchmark requires no interrupts or exceptions");
            if(cpu.instret_increment) begin
                retired=retired+1;
                $fdisplay(trace_fd,"%08x %02x",cpu.id_ex_inst0_pc_out,cpu.id_ex_inst0_instr_id_out);
            end
            if(!GATED && wren) check_store(wraddr,wdata,strb);
            if(!GATED && rden) begin
                if(rdaddr!==32'h10010000) $fatal(1,"unexpected load");
                data_reads=data_reads+1;
            end
            if(cpu.mem_wb_inst0_pc_out>=32'h80000000 && cpu.mem_wb_inst0_pc_out<32'h80020000 &&
               div_present[(cpu.mem_wb_inst0_pc_out-32'h80000000)>>2] &&
               cpu.mem_wb_inst0_rd_valid_out &&
               (cpu.mem_wb_inst0_instr_id_out==INSTR_MUL || cpu.mem_wb_inst0_instr_id_out==INSTR_MULH ||
                cpu.mem_wb_inst0_instr_id_out==INSTR_MULHSU || cpu.mem_wb_inst0_instr_id_out==INSTR_MULHU)) begin
                if(cpu.wb_inst0_rd_value_out!==div_expected[(cpu.mem_wb_inst0_pc_out-32'h80000000)>>2])
                    $fatal(1,"incorrect multiply WB");
                written=written+1;
            end
        end
    end
"""+tb[end:]
start=tb.index("        repeat(5) @(negedge clk); rst=0;")
end=tb.index("        wait(seen==stores);",start)
tb=tb[:start]+"        repeat(5) @(negedge clk); rst=0;\n"+tb[end:]
start=tb.index("        if(launched!=divisions+1")
end=tb.index("        if(data_reads!=1)",start)
tb=tb[:start]+"        if(written!=divisions) $fatal(1,\"missing/duplicate MUL WB\");\n"+tb[end:]
start=tb.index('        $display("PASS GATED=')
end=tb.index("        $finish;",start)
tb=tb[:start]+"""        $fclose(trace_fd);
        $display("PASS WORKLOAD GATED=%0d muls=%0d stores=%0d CPU_edges=%0d system_cycles=%0d instructions=%0d",
                 GATED,written,seen,edges,cycles,retired);
"""+tb[end:]
test=out/"cpu_m_workload_tb.sv";test.write_text(tb)
source=ROOT.parent/"synapse32"
results={"harness_sha256":hashlib.sha256(test.read_bytes()).hexdigest(),
         "ipc_definition":"instret completions / enabled CPU edges; fixed no-fault/no-interrupt program with drain",
         "runs":{}}
for label,build in (("baseline",args.baseline.resolve()),("candidate",args.candidate.resolve())):
    run_test=test
    if label=="candidate" and args.candidate_system_mul:
        run_test=out/"cpu_m_system_workload_tb.sv"
        run_test.write_text(tb.replace("riscv_cpu cpu (",
            "riscv_cpu #(.SYSTEM_MUL(GATED)) cpu (\n        .system_clk(clk),"))
    files=[build/"overlay"/n for n in ("riscv_cpu.v","execution_unit.v","alu.v","divider.v")]
    files += [source/"rtl"/n for n in ("memory_unit.v","writeback.v")]
    files += [p for d in ("core_modules","pipeline_stages") for p in sorted((source/"rtl"/d).glob("*.v"))
              if p.name not in ("alu.v","divider.v")]
    for gated in (0,1):
        tag=f"{label}-gated{gated}";obj=out/("obj-"+tag)
        command=["verilator","--binary","--timing","-j","2","-Wno-fatal","--top-module","cpu_m_workload_tb",
                 f"-GGATED={gated}","--Mdir",obj,"-DSYNAPSE32_CLOCK_SIM","-DSYNAPSE32_FORWARD_ASSERT",
                 "-DSYNAPSE32_SYSTEM_MUL_ASSERT","-I"+str(source/"rtl/include"),*files,ROOT/"hardware/synapse32/synapse32_memory_sequencer.sv",
                 ROOT/"hardware/synapse32/synapse32_clock_enable.sv",run_test]
        print("Running",tag,flush=True)
        with (out/(tag+"-compile.log")).open("w") as log:
            subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,check=True)
        with (out/(tag+".log")).open("w") as log:
            subprocess.run([str(obj/"Vcpu_m_workload_tb"),"+trace="+str(out/(tag+".trace"))],
                           stdout=log,stderr=subprocess.STDOUT,check=True)
        summary=next(l for l in (out/(tag+".log")).read_text().splitlines() if l.startswith("PASS WORKLOAD"))
        counts={k:int(v) for k,v in re.findall(r"(\w+)=(\d+)",summary)}
        trace=(out/(tag+".trace")).read_bytes()
        assert len(trace.splitlines())==counts["instructions"], "incomplete instruction trace"
        results["runs"][tag]={"summary":summary,**counts,
            "harness_sha256":hashlib.sha256(run_test.read_bytes()).hexdigest(),
            "cpu_ipc":counts["instructions"]/counts["CPU_edges"],
            "instructions_per_system_cycle":counts["instructions"]/counts["system_cycles"],
            "trace_sha256":hashlib.sha256(trace).hexdigest(),
            "source_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
        print(summary,flush=True)
results["comparisons"]={}
for gated in (0,1):
    base=results["runs"][f"baseline-gated{gated}"]
    candidate=results["runs"][f"candidate-gated{gated}"]
    same_trace=base["trace_sha256"]==candidate["trace_sha256"]
    preserves_ipc=same_trace and candidate["cpu_ipc"]>=base["cpu_ipc"]
    results["comparisons"][f"gated{gated}"]={"same_instruction_trace":same_trace,
        "preserves_cpu_ipc":preserves_ipc,"cpu_ipc_ratio":candidate["cpu_ipc"]/base["cpu_ipc"]}
    print(f"GATED={gated}: IPC {base['cpu_ipc']:.6f} -> {candidate['cpu_ipc']:.6f}; "
          f"same trace={same_trace}; preserves IPC={preserves_ipc}",flush=True)
results["accepted"]=all(c["preserves_cpu_ipc"] for c in results["comparisons"].values())
(out/"results.json").write_text(json.dumps(results,indent=2)+"\n")
if not results["accepted"]:
    raise SystemExit("REJECTED: candidate must preserve the instruction trace and CPU IPC")
