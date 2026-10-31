"""Generate static mesh/rotation ROMs; no animated vertices or pixels are stored."""
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]


def data():
    mesh = json.loads((ROOT / "assets/mesh.json").read_text())
    rotations = []
    elevation = math.radians(20)
    for phase in range(256):
        angle = phase * math.tau / 256
        c, s = math.cos(angle), math.sin(angle)
        ce, se = math.cos(elevation), math.sin(elevation)
        # Row vectors: rotate around Y, then tilt around X.
        rotations.append([[round(127 * x) for x in row] for row in
                          ((c, s*se, -s*ce, 0), (0, ce, se, 0),
                           (s, -c*se, c*ce, 0), (0, 0, 0, 0))])
    shades = []
    for face in mesh["faces"]:
        a, b, c = [mesh["vertices"][i] for i in face]
        u, v = [[p-q for p, q in zip(point, a)] for point in (b, c)]
        n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        length = math.sqrt(sum(x*x for x in n)) or 1
        # Object-space, two-sided baked lighting; geometry rotates live on TPU.
        light = abs((n[0]*0.2+n[1]*0.65+n[2]*0.73)/length)
        shades.append(min(15, max(3, round(4 + 11*light))))
    return mesh, rotations, shades


def generate():
    mesh, rotations, shades = data()
    out = ROOT / "assets"
    vertices = [x & 255 for v in mesh["vertices"] for x in (*v, 0)]
    vertices += [0] * (1024-len(vertices))
    faces = [f[0] | (f[1] << 8) | (f[2] << 16) | (shade << 24)
             for f, shade in zip(mesh["faces"], shades)]
    faces += [0] * (512-len(faces))
    for name, words, digits in (
        ("vertices.hex", vertices, 2),
        ("rotations.hex", [x & 255 for m in rotations for row in m for x in row], 2),
        ("faces.hex", faces, 7),
    ):
        path = out/name
        contents = "".join(f"{word:0{digits}x}\n" for word in words)
        if not path.exists() or path.read_text() != contents:
            path.write_text(contents)
    assert len(mesh["vertices"]) == 204 and len(mesh["faces"]) == 407
    for matrix in rotations:
        for v in mesh["vertices"]:
            q = [sum(v[k]*matrix[k][j] for k in range(3)) for j in range(3)]
            assert 0 <= 80+(q[0] >> 8) < 160
            assert 16 <= 78-(q[1] >> 8) < 128
            assert 0 <= 128+(q[2] >> 7) < 255
    print("ROMs: 204 vertices, 407 triangles, 256 rotation matrices; all projections bounded")


if __name__ == "__main__":
    generate()
