#!/usr/bin/env python3
"""Compile one private router2 translation unit, reuse existing read-only objects."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--build", type=Path, required=True)
p.add_argument("--router-source", type=Path, required=True)
args = p.parse_args()
build, source = args.build.resolve(), args.router_source.resolve()
out = source.parent
commands = subprocess.check_output(["ninja", "-C", str(build), "-t", "commands", "nextpnr-xilinx"], text=True).splitlines()
obj = "CMakeFiles/nextpnr-xilinx.dir/common/router2.cc.o"
compile_cmd = shlex.split(next(c for c in commands if " -c " in c and " -o " + obj + " " in c))
for flag, value in (("-o", str(out / "router2.cc.o")), ("-MF", str(out / "router2.cc.o.d")),
                    ("-MT", str(out / "router2.cc.o")), ("-c", str(source))):
    compile_cmd[compile_cmd.index(flag) + 1] = value
link_line = next(c for c in commands if " -o nextpnr-xilinx " in c)
assert link_line.startswith(": && ") and link_line.endswith(" && :")
link_cmd = shlex.split(link_line[5:-5])
link_cmd[link_cmd.index(obj)] = str(out / "router2.cc.o")
link_cmd[link_cmd.index("-o") + 1] = str(out / "nextpnr-xilinx")
objects = {str((build / s).resolve()): hashlib.sha256((build / s).read_bytes()).hexdigest()
           for s in link_cmd if s.endswith(".o") and not s.startswith(str(out))}
(out / "build-manifest.json").write_text(json.dumps(dict(compile=compile_cmd, link=link_cmd,
    reused_objects_sha256=objects, private_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()), indent=2) + "\n")
for command in (compile_cmd, link_cmd):
    subprocess.run(command, cwd=build, check=True)
print(out / "nextpnr-xilinx")
