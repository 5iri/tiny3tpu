#!/usr/bin/env python3
"""Route an unchanged recorded netlist with an explicit placement variant."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from synapse32_timing_report import summarize

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--parent",type=Path,required=True,help="Existing route-manifest.json")
parser.add_argument("--out",type=Path,required=True)
parser.add_argument("--beta",type=float)
parser.add_argument("--alpha",type=float,help="HeAP anchoring weight; default remains tool-defined")
parser.add_argument("--placer",choices=["heap","sa"],default="heap")
parser.add_argument("--seed",type=int,default=4)
args=parser.parse_args()
if args.beta is not None and not 0<args.beta<=1: parser.error("beta must be in (0,1]")
if args.alpha is not None and not 0<args.alpha<=1: parser.error("alpha must be in (0,1]")
if args.placer=="sa" and (args.beta is not None or args.alpha is not None): parser.error("alpha/beta apply only to heap")
parent=args.parent.resolve();record=json.loads(parent.read_text())
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for name,sha in record["sha256"].items():
    if digest(name)!=sha: raise SystemExit("Stale source: "+name)
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
command=list(record["command"])
for flag,value in (("--write",out/"routed.json"),("--report",out/"report.json"),("--log",out/"route.log"),("--seed",args.seed)):
    command[command.index(flag)+1]=str(value)
assert command[command.index("--freq")+1]=="100"
assert not any(flag in command for flag in ("--force","--timing-allow-fail","--ignore-loops","--fasm"))
if "--placer" in command: command[command.index("--placer")+1]=args.placer
else: command += ["--placer",args.placer]
environment={k:v for k,v in os.environ.items() if not k.startswith("NEXTPNR_")}
placement_environment={}
if args.beta is not None:
    placement_environment["NEXTPNR_PLACER_BETA"]=str(args.beta)
if args.alpha is not None:
    placement_environment["NEXTPNR_PLACER_ALPHA"]=str(args.alpha)
environment.update(placement_environment)
manifest={"parent":str(parent),"parent_sha256":digest(parent),"command":command,
          "placement_environment":placement_environment,
          "sha256":record["sha256"],"driver_sha256":digest(__file__),
          "scope":"Unchanged RTL/netlist/firmware/constraints; placement algorithm/settings and explicit seed only"}
(out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
with (out/"console.log").open("w") as log:
    result=subprocess.run(command,env=environment,stdout=log,stderr=subprocess.STDOUT)
manifest["inputs_unchanged"]=all(digest(n)==sha for n,sha in record["sha256"].items())
manifest["timing"]=summarize((out/"route.log").read_text(),exit_code=result.returncode)
(out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print(json.dumps(manifest["timing"],indent=2))
if not manifest["inputs_unchanged"] or not manifest["timing"]["accepted"]: raise SystemExit(1)
