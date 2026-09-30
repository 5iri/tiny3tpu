#!/usr/bin/env python3
"""Capture execution control in the existing system-clock gaps, with late IRQ priority."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("system_alu", HERE.parent / "system-alu/run.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
run = base.run

# Operand outputs and CSR address/read-enable remain combinational: they feed
# the divider and CSR read path, rather than the final execution control.
OUTPUTS = {
    "exec_output": 32, "jump_signal": 1, "jump_addr": 32, "mem_addr": 32,
    "flush_pipeline": 1, "interrupt_taken": 1, "mret_instruction": 1,
    "sret_instruction": 1, "trap_to_supervisor": 1, "ecall_exception": 1,
    "ebreak_exception": 1, "illegal_instruction_exception": 1,
    "instruction_address_misaligned_exception": 1,
    "load_address_misaligned_exception": 1,
    "store_address_misaligned_exception": 1, "exception_tval": 32,
    "wfi_instruction": 1,
}


def prepare(out):
    overlay = base.prepare(out)
    path = overlay / "execution_unit.v"
    original = path.read_text()
    (out / "execution_reference.v").write_text(original.replace("module execution_unit #", "module execution_reference #", 1))
    header, body = original.split("// Internal signals", 1)
    # Only rename signal identifiers, not submodule port names (e.g. .pc_input).
    for name in OUTPUTS:
        body = re.sub(r"(?<!\.)\b" + name + r"\b", name + "_comb", body)
    assert body.count("if (interrupt_pending) begin") == 1
    body = body.replace("if (interrupt_pending) begin", "if (1'b0) begin", 1)
    declarations = "\n".join(
        f"reg [{width-1}:0] {name}_comb, {name}_q;" for name, width in OUTPUTS.items())
    registers = "always @(posedge system_clk) begin\n    if(system_rst) begin\n"
    registers += "\n".join(f"        {name}_q <= 0;" for name in OUTPUTS)
    registers += "\n    end else begin\n"
    registers += "\n".join(f"        {name}_q <= {name}_comb;" for name in OUTPUTS)
    registers += "\n    end\nend\n"
    selection = "always @* begin\n"
    for name in OUTPUTS:
        condition = "SYSTEM_MUL && !alu_is_mul" if name == "exec_output" else "SYSTEM_MUL"
        selection += f"    {name} = {condition} ? {name}_q : {name}_comb;\n"
    selection += "    if(interrupt_pending) begin\n"
    irq_values = {"jump_signal": "1'b1", "flush_pipeline": "1'b1", "interrupt_taken": "1'b1",
                  "trap_to_supervisor": "interrupt_to_supervisor",
                  "jump_addr": "interrupt_to_supervisor ? stvec : mtvec"}
    selection += "\n".join(f"        {name} = {irq_values.get(name, '0')};" for name in OUTPUTS)
    selection += "\n    end\nend\n"
    path.write_text(header + declarations + "\n// Internal signals" +
                    body.replace("endmodule", registers + selection + "endmodule", 1))
    # At each enabled CPU edge, compare every registered control/data result
    # against the current unregistered result. Late IRQ deliberately bypasses
    # these registers and is checked separately by the execution test.
    cpu_path = overlay / "riscv_cpu.v"
    cpu = cpu_path.read_text()
    assertions = "        always @(posedge clk) if(!rst && !ex_unit_inst0.interrupt_pending) begin\n"
    for name in OUTPUTS:
        assertions += f"            if(ex_unit_inst0.{name} !== ex_unit_inst0.{name}_comb)\n"
        assertions += f'                $fatal(1,"Stale execution control {name} pc=%h",id_ex_inst0_pc_out);\n'
    assertions += "        end\n"
    marker = "        wire signed [32:0] a_ref"
    assert marker in cpu
    cpu_path.write_text(cpu.replace(marker, assertions + marker, 1))
    return overlay


def verify_execution(out, overlay):
    # Check all outputs at the earliest legal CPU edge. Data/architectural
    # inputs stay stable during the gap; IRQ and its target may change at the
    # last falling edge, with no intervening system rising edge.
    header = (overlay / "execution_unit.v").read_text().split("// Internal signals")[0]
    header = header.replace("input wire system_clk, system_rst,", "input wire system_clk,\ninput wire system_rst,")
    ports = re.findall(r"(input|output)\s+(?:wire|reg)\s*(\[[^\]]+\])?\s*(\w+)", header)
    inputs = [(w, n) for direction, w, n in ports if direction == "input"]
    outputs = [(w, n) for direction, w, n in ports if direction == "output"]
    tb = "module execution_control_tb;\n"
    tb += "\n".join("reg " + w + " " + n + ";" for w, n in inputs) + "\n"
    tb += "always #5 system_clk=~system_clk;\ninteger i,j,checked=0;\n"
    tb += "reg [31:0] rng=32'h73528a91;\nfunction [31:0] random32; begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);random32=rng;end endfunction\n"
    for label, module, mode in (("gold", "execution_reference", 0), ("gate", "execution_unit", 1)):
        tb += "\n".join("wire " + w + " " + label + "_" + n + ";" for w, n in outputs) + "\n"
        connections = ["." + n + "(" + n + ")" for w, n in inputs]
        connections += ["." + n + "(" + label + "_" + n + ")" for w, n in outputs]
        tb += f"{module} #(.SYSTEM_MUL({mode})) {label}(" + ",".join(connections) + ");\n"
    tb += "task check;begin\n"
    for w, n in outputs:
        tb += f'if(gold_{n} !== gate_{n}) $fatal(1,"execution {n} i=%d op=%h id=%h irq=%b gold=%h gate=%h",i,opcode,instr_id,interrupt_pending,gold_{n},gate_{n});\n'
    tb += "checked=checked+1;end endtask\ninitial begin\n"
    tb += "\n".join(f"{n}=0;" for w, n in inputs) + "\n"
    tb += "system_rst=1;repeat(4) @(negedge system_clk);system_rst=0;\n"
    tb += "for(i=0;i<32768;i=i+1) begin\n"
    tb += "\n".join(f"{n}=random32();" for w, n in inputs if n not in ("system_clk", "system_rst", "interrupt_pending"))
    tb += "\ninstr_id=i[6:0];opcode=i[13:7];interrupt_pending=0;\n"
    tb += "repeat(3) @(posedge system_clk);#1;check();\n"
    tb += "@(negedge system_clk);interrupt_pending=1;interrupt_to_supervisor=~interrupt_to_supervisor;#1;check();\n"
    tb += "interrupt_pending=0;#1;check();\nend\n"
    tb += '$display("PASS execution control: %0d comparisons including last-half-cycle IRQ assertion/removal",checked);$finish;end\nendmodule\n'
    (out / "execution_control_tb.sv").write_text(tb)
    source = ROOT.parent / "synapse32"
    run(["iverilog", "-g2012", "-s", "execution_control_tb", "-I" + str(source / "rtl/include"),
         "-o", out / "execution.vvp", overlay / "execution_unit.v", out / "execution_reference.v",
         overlay / "alu.v", source / "rtl/core_modules/csr_exec.v", out / "execution_control_tb.sv"], out / "execution-compile.log")
    run(["vvp", out / "execution.vvp"], out / "execution.log")
    print((out / "execution.log").read_text(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "execution", "verify"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    overlay = prepare(out)
    if args.mode in ("execution", "verify"):
        verify_execution(out, overlay)
    if args.mode == "verify":
        base.prove(out)
        base.base.base.verify(out, overlay, unit=False)
    paths = list(overlay.glob("*.v")) + [Path(__file__)] + list(out.glob("*reference.v")) + list(out.glob("*tb.sv"))
    (out / (args.mode + "-sources.json")).write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, indent=2) + "\n")


if __name__ == "__main__":
    main()
