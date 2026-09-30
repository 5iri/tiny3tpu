#!/usr/bin/env python3
"""Select the final MUL register directly, avoiding unrelated EX/CSR mux paths."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("divider_payload",HERE.parent / "divider-payload/run.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
control = base.load("execution_validation","system-control/run.py")


def prepare(out):
    overlay = base.prepare(out)
    path = overlay / "execution_unit.v"; source = path.read_text()
    old = "    exec_output = SYSTEM_MUL && !alu_is_mul ? exec_output_q : exec_output_comb;"
    new = '''    // Only R/I ALU output needs the final +3 MUL value. All other
    // execution results are ready in exec_output_q at +3, including the
    // arbitrary opcode/instruction-ID combinations exercised by validation.
    exec_output = SYSTEM_MUL ?
        ((alu_is_mul && (opcode==7'b0110011 || opcode==7'b0010011)) ?
            alu_inst.ALUoutput : exec_output_q) : exec_output_comb;'''
    assert source.count(old)==1
    path.write_text(source.replace(old,new,1))
    return overlay


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("prepare","verify")); parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(); out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    overlay=prepare(out)
    if args.mode=="verify":
        control.verify_execution(out,overlay)
        base.validation.verify(out,overlay,unit=False)
    paths=list(overlay.glob("*.v"))+[Path(__file__)]
    (out/(args.mode+"-sources.json")).write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+"\n")
