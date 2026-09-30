#!/usr/bin/env python3
"""Exercise aggregate DMA command errors through the actual RV32IM driver."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reference", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
ref = args.reference.resolve()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]
reference = json.loads((ref / "system/results.json").read_text())
for name, digest in reference["sha256"].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, "Stale reference: " + name
firmware = (ref / "stream_smoke.c").read_text()
marker = "    if (tiny3tpu_dma_init(&dma)) return 12;"
assert firmware.count(marker) == 1
firmware = firmware.replace(marker, marker + '''
    /* First, middle and last command must be reflected in aggregate ERROR
     * before DONE. The driver acknowledges completion and remains poisoned
     * until explicitly reinitialized; a poisoned resubmission must do no IO. */
    for (unsigned fault=0;fault<3;++fault) {
        for (unsigned i=0;i<193;++i) {
            dma.commands[2*i]=(i==fault*96) ? 0xfc : 0x10;
            dma.commands[2*i+1]=0;
        }
        if (tiny3tpu_dma_submit(&dma,193)!=-1 || dma.poisoned!=1) return 20;
        if (dma.registers[4]!=0) return 21;
        if (tiny3tpu_dma_submit(&dma,1)!=-1 || dma.registers[4]!=0) return 22;
        if (tiny3tpu_dma_init(&dma) || dma.poisoned) return 23;
    }
''')
(out / "firmware.c").write_text(firmware)
cmake = (ref / "system/run.cmake").read_text().replace(str(ref / "stream_smoke.c"), str(out / "firmware.c"))
assert str(out / "firmware.c") in cmake
(out / "run.cmake").write_text(cmake)
command = ["-DBINARY_DIR=" + str(out) if a.startswith("-DBINARY_DIR=") else str(out / "run.cmake") if a == str(ref / "system/run.cmake") else a for a in reference["command"]]
with (out / "run.log").open("w") as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
result = {"passed": True, "error_positions": [0, 96, 192],
          "checks": "RV32IM submit error return, completion acknowledgment, poisoning, rejected resubmission, explicit reinitialization, then original GEMM scoreboard",
          "command": command}
paths = [Path(__file__), root / "src/dma_backend.c", out / "firmware.c", out / "run.cmake", out / "smoke.bin", ref / "system/results.json"]
result["sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
(out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
print("PASS RV32IM DMA firmware: three aggregate command errors, poison/reinit, original GEMM scoreboard")
