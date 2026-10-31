"""Independent scalar matrix multiplication and direct edge-function rasterizer."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'banana_scene/tools'))
from assets import data

PHASES = list(range(0, 256, 16))


def reference(phase):
    mesh, matrices, shades = data()
    m = matrices[phase]
    transformed = [[sum(v[k]*m[k][j] for k in range(3)) for j in range(3)]
                   for v in mesh["vertices"]]
    return transformed, rasterize(transformed)


def rasterize(transformed, cpu=False):
    if cpu:
        from mesh_assets import data as cpu_data
        mesh, shades = cpu_data()
    else:
        mesh, _, shades = data()
    vertices = [(320+(q[0]//64), 280-(q[1]//64), 128+(q[2]//128)) for q in transformed]
    assert all(0 <= x < 640 and 0 <= y < 480 and 0 <= z < 255 for x,y,z in vertices)
    pixels, depths = [0]*307200, [255]*307200

    def edge(a, b, x, y):
        return (b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])

    for face, shade in zip(mesh["faces"], shades):
        a, b, c = [vertices[i] for i in face]
        area = edge(a, b, *c[:2])
        if area == 0:
            continue
        z = (a[2]+b[2]+c[2])//3
        for y in range(min(a[1], b[1], c[1]), max(a[1], b[1], c[1])+1):
            for x in range(min(a[0], b[0], c[0]), max(a[0], b[0], c[0])+1):
                edges = [edge(p, q, x, y) for p, q in ((a,b),(b,c),(c,a))]
                if min(edges) >= 0 or max(edges) <= 0:
                    i = y*640+x
                    if z < depths[i]:
                        if cpu:
                            numerator = edges[0]*shade[2]+edges[1]*shade[0]+edges[2]*shade[1]
                            if area<0: numerator=-numerator
                            value=(numerator+abs(area)//2)//abs(area)
                        else:value=shade
                        pixels[i], depths[i] = value, z
    return pixels

