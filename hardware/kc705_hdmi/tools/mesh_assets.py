"""Build a denser HDMI mesh and Gouraud face ROM from the pinned jaxsim OBJ."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
ASSETS = Path(__file__).resolve().parents[1] / 'assets'
SOURCE_SHA256 = 'f0f8267c7f7cfc64430cb5f8ee6dfa9b1ec7cac6109a39ad96e89f7a57433098'


def data():
    mesh = json.loads((ASSETS / 'mesh.json').read_text())
    return mesh, [[mesh['vertex_shades'][i] for i in f] for f in mesh['faces']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Pinned original jaxsim banana OBJ')
    parser.add_argument('--grid', type=int, default=36)
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    if args.source:
        import numpy as np
        sys.path.insert(0, str(ROOT))
        from sidequests.banana.render import reduce_mesh
        assert hashlib.sha256(args.source.read_bytes()).hexdigest() == SOURCE_SHA256
        vertices, faces = [], []
        for line in args.source.read_text().splitlines():
            row = line.split()
            if not row: continue
            if row[0] == 'v': vertices.append(list(map(float, row[1:4])))
            elif row[0] == 'f':
                ids = [int(s.split('/')[0])-1 for s in row[1:]]
                faces.extend([ids[0], ids[i], ids[i+1]] for i in range(1, len(ids)-1))
        source_counts = [len(vertices), len(faces)]
        vertices, faces = reduce_mesh(np.asarray(vertices, np.float32), np.asarray(faces, np.int32), args.grid, np)
        vertices -= (vertices.min(axis=0)+vertices.max(axis=0))/2
        # Area-weighted normals use floating-point geometry before quantization,
        # so INT8 rounding does not create artificial lighting facets.
        tri = vertices[faces]
        normals = np.cross(tri[:,1]-tri[:,0], tri[:,2]-tri[:,0])
        vertex_normals = np.zeros_like(vertices)
        for corner in range(3): np.add.at(vertex_normals, faces[:,corner], normals)
        quantized = np.rint(vertices*(110./float(np.abs(vertices).max()))).astype(np.int8)
        # Weld equal quantized positions and remove faces collapsed by INT8.
        quantized, mapping = np.unique(quantized, axis=0, return_inverse=True)
        combined = np.zeros((len(quantized),3), np.float32)
        np.add.at(combined, mapping, vertex_normals)
        faces = mapping[faces]
        tri = quantized[faces].astype(np.int32)
        valid = np.any(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]) != 0, axis=1)
        collapsed = int((~valid).sum());faces = faces[valid]
        _, unique = np.unique(np.sort(faces,axis=1), axis=0, return_index=True)
        faces = faces[np.sort(unique)]
        used, remap = np.unique(faces, return_inverse=True)
        quantized, combined, faces = quantized[used], combined[used], remap.reshape(-1,3)
        length = np.linalg.norm(combined,axis=1)
        assert np.all(length > 0)
        light = np.abs(combined @ np.array([.2,.65,.73]) / length)
        shades = np.clip(np.rint(4*(4+11*light)),12,60).astype(int)
        mesh = dict(source='SRA-VJTI/jaxsim c0a097bba1c6db10cac7b359fbac11cfedc48c6b examples/sampledata/banana.obj',
                    source_sha256=SOURCE_SHA256, source_vertices=source_counts[0], source_triangles=source_counts[1],
                    reduction_grid=[args.grid]*3, collapsed_faces_removed=collapsed,
                    quantization='Bounding-box centered, INT8 +/-110; coincident positions welded',
                    lighting='Area-weighted vertex normals before quantization; two-sided baked light; Gouraud interpolation',
                    vertices=quantized.tolist(), faces=faces.tolist(), vertex_shades=shades.tolist())
        (ASSETS/'mesh.json').write_text(json.dumps(mesh,separators=(',', ':'))+'\n')
    mesh, shades = data();nv,nt=len(mesh['vertices']),len(mesh['faces'])
    assert nv<=4096 and nt<=8192
    words = [a | b<<12 | c<<24 | s[0]<<36 | s[1]<<42 | s[2]<<48
             for (a,b,c),s in zip(mesh['faces'],shades)]
    words += [0]*(8192-len(words))
    (ASSETS/'faces.hex').write_text(''.join(f'{w:014x}\n' for w in words))
    (ASSETS/'mesh_config.vh').write_text(
        '`ifndef KC705_HDMI_MESH_CONFIG\n`define KC705_HDMI_MESH_CONFIG\n'+
        f'`define HDMI_VERTICES {nv}\n`define HDMI_TRIANGLES {nt}\n'+
        '`define HDMI_VERTEX_BITS 12\n`define HDMI_FACE_BITS 13\n'+
        '`define HDMI_BOOT_WORDS 65536\n`define HDMI_ANIMATION_PERIOD 840000\n`endif\n')
    print(f'HDMI CPU mesh: {nv} vertices, {nt} triangles; smooth vertex lighting')


if __name__ == '__main__': main()
