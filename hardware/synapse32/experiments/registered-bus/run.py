#!/usr/bin/env python3
"""Check and route registered bus requests with a previously built CPU overlay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from prepare import prepare,ROOT,HERE

os.environ.update(OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2")


def run(command,log,check=True):
    print("Running",log.name,flush=True)
    with log.open("w") as f:
        rc=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT).returncode
    if check and rc:
        print(log.read_text(errors="replace")[-5000:]);raise SystemExit(rc)
    return rc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("verify","synth","route"))
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--cpu-build",type=Path,default=ROOT/"build-ddr-mul")
    parser.add_argument("--seed",type=int,default=4)
    parser.add_argument("--abc9",action="store_true",help="Use timing-aware ABC9 mapping; no RTL or cycle change")
    args=parser.parse_args();out=args.out.resolve();cpu=args.cpu_build.resolve()
    candidate=prepare(out);source=ROOT.parent/"synapse32"
    if args.mode=="verify":
        run(["iverilog","-g2012","-s","tb_synapse32_memory_sequencer","-o",out/"sequencer.vvp",
             candidate,ROOT/"tests/tb_synapse32_memory_sequencer.sv"],out/"unit-compile.log")
        run(["vvp",out/"sequencer.vvp"],out/"unit.log")
        cmake=(ROOT/"tests/run_synapse32_cpu_test.cmake").read_text().replace(
            "${SOURCE_DIR}/hardware/synapse32/synapse32_memory_sequencer.sv",str(candidate))
        (out/"dram.cmake").write_text(cmake)
        run(["cmake","-DSOURCE_DIR="+str(ROOT),"-DBINARY_DIR="+str(out/"dram"),
             "-DSYNAPSE32_DIR="+str(source),"-DCPU_OVERLAY_DIR="+str(cpu/"overlay"),
             "-DVERILATOR=verilator","-DRISCV_GCC=riscv64-unknown-elf-gcc",
             "-DRISCV_OBJCOPY=riscv64-unknown-elf-objcopy","-DDRAM_TEST=ON",
             "-P",out/"dram.cmake"],out/"dram.log")
        print((out/"unit.log").read_text()+(out/"dram.log").read_text(),flush=True)
    elif args.mode=="synth":
        board=out/"board";board.mkdir(exist_ok=True)
        script=(cpu/"board/synth.ys").read_text()
        old=str(ROOT/"hardware/synapse32/synapse32_memory_sequencer.sv")
        assert script.count(old)==1
        script=script.replace(old,str(candidate)).replace(str(cpu/"board/soc.json"),str(board/"soc.json"))
        if args.abc9:
            script=script.replace("synth_xilinx -family xc7", "synth_xilinx -abc9 -family xc7")
        (board/"synth.ys").write_text(script)
        for name in ("kc705.xdc","firmware.hex"):
            (board/name).write_bytes((cpu/"board"/name).read_bytes())
        run(["/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys","-Q","-T","-m","slang",
             "-s",board/"synth.ys"],board/"synth.log")
    else:
        board=out/"board"
        tool=Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx")
        chipdb=Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin")
        command=[tool,"--chipdb",chipdb,"--xdc",board/"kc705.xdc","--freq","100",
                 "--seed",str(args.seed),"--json",board/"soc.json","--write",board/"routed.json",
                 "--report",board/"report.json","--log",board/"route.log"]
        manifest={"command":list(map(str,command)),"seed":args.seed}
        paths=[candidate,board/"synth.ys",board/"soc.json",board/"kc705.xdc",board/"firmware.hex",tool,chipdb]
        paths+=sorted((cpu/"overlay").glob("*.v"))
        manifest["sha256"]={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        (board/"route-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        rc=run(command,board/"route-console.log",check=False)
        sys.path.insert(0,str(ROOT))
        from tools.synapse32_timing_report import summarize
        manifest["timing"]=summarize((board/"route.log").read_text(),exit_code=rc)
        (board/"route-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        print(json.dumps(manifest["timing"]["final_clocks"],indent=2),flush=True)
        if not manifest["timing"]["accepted"]:
            print("REJECTED:",manifest["timing"]["reasons"],flush=True);raise SystemExit(1)


if __name__=="__main__":main()
