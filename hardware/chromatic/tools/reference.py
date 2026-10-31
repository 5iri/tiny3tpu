"""Independent scalar matrix multiplication and direct edge-function rasterizer."""
from pathlib import Path
from assets import ROOT, data

PHASES = list(range(0, 256, 16))


def reference(phase):
    mesh, matrices, shades = data()
    m = matrices[phase]
    transformed = [[sum(v[k]*m[k][j] for k in range(3)) for j in range(3)]
                   for v in mesh["vertices"]]
    vertices = [(80+(q[0]//256), 78-(q[1]//256), 128+(q[2]//128)) for q in transformed]
    pixels, depths = [0]*23040, [255]*23040

    def edge(a, b, x, y):
        return (b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])

    for face, shade in zip(mesh["faces"], shades):
        a, b, c = [vertices[i] for i in face]
        if edge(a, b, *c[:2]) == 0:
            continue
        z = (a[2]+b[2]+c[2])//3
        for y in range(min(a[1], b[1], c[1]), max(a[1], b[1], c[1])+1):
            for x in range(min(a[0], b[0], c[0]), max(a[0], b[0], c[0])+1):
                edges = [edge(p, q, x, y) for p, q in ((a,b),(b,c),(c,a))]
                if min(edges) >= 0 or max(edges) <= 0:
                    i = y*160+x
                    if z < depths[i]:
                        pixels[i], depths[i] = shade, z
    return transformed, pixels


def generate():
    out = ROOT / "build"
    out.mkdir(exist_ok=True)
    with (out/"expected-results.hex").open("w") as results, (out/"expected-pixels.hex").open("w") as pixels:
        for phase in PHASES:
            q, image = reference(phase)
            results.write("".join(f"{v & 0xffffffff:08x}\n" for row in q for v in row))
            pixels.write("".join(f"{v:x}\n" for v in image))


if __name__ == "__main__":
    generate()
