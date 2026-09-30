#!/usr/bin/env python3
"""Verify, synthesize and diagnostically route the isolated MUL pipeline."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from prepare import prepare, benches, divider_benches, HERE, ROOT, BASE

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
spec = importlib.util.spec_from_file_location("retime", HERE.parent / "forward-retime/run.py")
retime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retime)
run = retime.run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("verify","synth","route"))
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--synapse32-dir",type=Path,default=ROOT.parent / "synapse32")
    parser.add_argument("--seed",type=int,default=4)
    parser.add_argument("--registered-divider",action="store_true")
    args=parser.parse_args()
    args.out=args.out.resolve(); args.out.mkdir(parents=True,exist_ok=True)
    args.synapse32_dir=args.synapse32_dir.resolve()
    out=args.out; overlay=prepare(out,args.registered_divider); benches(out)
    if args.mode=="verify":
        run(["iverilog","-g2012","-s","multiply_tb","-o",out/"multiply.vvp",
             HERE/"multiply.sv",HERE/"multiply_tb.sv"],out/"multiply-compile.log")
        run(["vvp",out/"multiply.vvp"],out/"multiply.log")
        print((out/"multiply.log").read_text(),flush=True)
        if args.registered_divider:
            retime.BASE=divider_benches(out)
            run(["iverilog","-g2012","-s","divider_tb","-o",out/"divider.vvp",
                 overlay/"divider.v",retime.BASE/"divider_tb.sv"],out/"divider-compile.log")
            run(["vvp",out/"divider.vvp"],out/"divider.log")
            print((out/"divider.log").read_text(),flush=True)
        # Existing DIV regression, collision checks, and real CPU/DRAM/TPU workload.
        retime.verify(args,overlay)
        files=[overlay/n for n in ("riscv_cpu.v","execution_unit.v","alu.v","divider.v")]
        files += [args.synapse32_dir/"rtl"/n for n in ("memory_unit.v","writeback.v")]
        files += [p for d in ("core_modules","pipeline_stages")
                  for p in sorted((args.synapse32_dir/"rtl"/d).glob("*.v"))
                  if p.name not in ("alu.v","divider.v")]
        for gated in (0,1):
            for bench in ("cpu_mul_tb","cpu_mul_collision_tb"):
                tag=f"{bench}-gated{gated}"; obj=out/("obj-"+tag)
                run(["verilator","--binary","--timing","-j","2","-Wno-fatal",
                     "--top-module",bench,f"-GGATED={gated}","--Mdir",obj,
                     "-DSYNAPSE32_CLOCK_SIM","-DSYNAPSE32_FORWARD_ASSERT",
                     "-I"+str(args.synapse32_dir/"rtl/include"),*files,
                     ROOT/"hardware/synapse32/synapse32_memory_sequencer.sv",
                     ROOT/"hardware/synapse32/synapse32_clock_enable.sv",out/(bench+".sv")],
                    out/(tag+"-compile.log"))
                run([obj/("V"+bench)],out/(tag+".log"))
                print("\n".join(l for l in (out/(tag+".log")).read_text().splitlines()
                                if l.startswith(("PASS GATED", "PASS CPU"))),flush=True)
    elif args.mode=="synth":
        run([ROOT/".venv-ddr-compat/bin/python",ROOT/"tools/kc705_open_build.py","synth",
             "--synapse32-dir",args.synapse32_dir,"--cpu-overlay-dir",overlay,
             "--build-dir",out/"board"],out/"synth-console.log")
    elif args.mode=="route":
        board=out/"board"
        tool=Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx")
        chipdb=Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin")
        command=[tool,"--chipdb",chipdb,"--xdc",board/"kc705.xdc","--freq","100",
                 "--seed",str(args.seed),"--json",board/"soc.json","--write",board/"routed.json",
                 "--report",board/"report.json","--log",board/"route.log"]
        manifest={"command":list(map(str,command)),"seed":args.seed}
        for name,path in (("tool",tool),("chipdb",chipdb),("netlist",board/"soc.json"),
                          ("xdc",board/"kc705.xdc"),("firmware",board/"firmware.hex")):
            manifest[name+"_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
        (board/"route-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        with (board/"route-console.log").open("w") as log:
            rc=subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT).returncode
        sys.path.insert(0,str(ROOT))
        from tools.synapse32_timing_report import summarize
        manifest["timing"]=summarize((board/"route.log").read_text(),exit_code=rc)
        (board/"route-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        print(json.dumps(manifest["timing"]["final_clocks"],indent=2),flush=True)
        if not manifest["timing"]["accepted"]:
            print("REJECTED:",manifest["timing"]["reasons"],flush=True)
            raise SystemExit(1)


if __name__=="__main__":
    main()
