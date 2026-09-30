#!/usr/bin/env python3
"""Embed the simulation's quantized mesh in the no-DDR live firmware."""
import argparse
import json
from pathlib import Path
import numpy as np

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", type=Path, default=Path("build-banana/render"))
    parser.add_argument("--out", type=Path, default=Path("build-banana/live"))
    args = parser.parse_args()
    mesh = np.load(args.render / "mesh.npz")
    report = json.loads((args.render / "report.json").read_text())
    vertices = np.rint(mesh["vertices"] * report["vertex_scale"]).astype(np.int8)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "banana_vertices.h").write_text(
        f"#define BANANA_VERTICES {len(vertices)}U\n"
        "static const signed char banana_vertices[] = {" +
        ",".join(str(int(v)) for v in vertices.reshape(-1)) + "};\n")
    print(f"Embedded {len(vertices)} vertices ({vertices.nbytes} bytes)")

if __name__ == "__main__":
    main()
