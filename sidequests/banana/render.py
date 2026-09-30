#!/usr/bin/env python3
"""Render jaxsim's banana with JAX or verified tiny3tpu RTL camera transforms."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
JAXSIM_COMMIT = "c0a097bba1c6db10cac7b359fbac11cfedc48c6b"
BATCH = 32
ROTATION_SCALE = 127


def reduce_mesh(vertices, faces, cells, np):
    """Cluster nearby vertices, retaining connected triangles rather than sampling faces."""
    lower, upper = vertices.min(axis=0), vertices.max(axis=0)
    keys = np.floor((vertices - lower) / np.maximum(upper - lower, 1e-9) * cells)
    keys = np.minimum(keys, cells - 1).astype(np.int32)
    _, mapping = np.unique(keys, axis=0, return_inverse=True)
    count = np.bincount(mapping)
    reduced = np.stack([np.bincount(mapping, weights=vertices[:, axis]) / count
                        for axis in range(3)], axis=1).astype(np.float32)
    triangles = mapping[faces]
    valid = ((triangles[:, 0] != triangles[:, 1]) &
             (triangles[:, 1] != triangles[:, 2]) &
             (triangles[:, 2] != triangles[:, 0]))
    triangles = triangles[valid]
    # Remove duplicate triangles regardless of winding, retaining the first winding.
    _, unique = np.unique(np.sort(triangles, axis=1), axis=0, return_index=True)
    triangles = triangles[np.sort(unique)].astype(np.int32)
    if not len(triangles):
        raise ValueError("mesh reduction removed every face; increase --cells")
    used, remap = np.unique(triangles, return_inverse=True)
    return reduced[used], remap.reshape(-1, 3).astype(np.int32)


def camera_rotation(renderer, jnp, np):
    # Derive the linear part from upstream look_at itself to preserve its conventions.
    eye = jnp.asarray(renderer.eye)
    points = jnp.concatenate([eye[None], eye[None] + jnp.eye(3)], axis=0)[None]
    mapped = np.asarray(renderer.look_at(points, eye))[0]
    return mapped[1:] - mapped[0]  # row-vector rotation, [3,3]


def write_fixture(out, model_bytes, inputs, expected, weights, bias):
    arrays = [("unsigned char", "banana_model", model_bytes),
              ("signed char", "banana_input", inputs.reshape(-1)),
              ("int", "banana_expected", expected.reshape(-1)),
              ("signed char", "banana_weights", weights.reshape(-1)),
              ("int", "banana_bias", bias.reshape(-1))]
    text = "/* Generated first camera batch; model/input/workspace fit on-chip. */\n"
    for ctype, name, values in arrays:
        text += f"static const {ctype} {name}[] = {{" + ",".join(str(int(v)) for v in values) + "};\n"
    (out / "banana_fixture.h").write_text(text)


def run(args):
    import imageio.v2 as imageio
    import jax
    import jax.numpy as jnp
    import numpy as np

    checkout = args.jaxsim.resolve()
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if commit != JAXSIM_COMMIT:
        raise ValueError(f"expected jaxsim {JAXSIM_COMMIT}, got {commit}")
    sys.path.insert(0, str(checkout))
    sys.path.insert(0, str(ROOT))
    from jaxsim.renderutils import SoftRenderer, TriangleMesh
    from tools.jax_export import export_function

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    mesh = TriangleMesh.from_obj(checkout / "examples/sampledata/banana.obj")
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    original_counts = {"vertices": len(vertices), "faces": len(faces)}
    # Same global centering and scale as softras_simple_render.py.
    vertices = (vertices - (vertices.max() + vertices.min()) / 2) * 5
    vertices, faces = reduce_mesh(vertices, faces, args.cells, np)
    np.savez(out / "mesh.npz", vertices=vertices, faces=faces)
    vertex_scale = 110.0 / float(np.abs(vertices).max())
    inputs = np.rint(vertices * vertex_scale).astype(np.int8)
    world = jnp.asarray(vertices[None])
    indices = jnp.asarray(faces[None])
    renderer = SoftRenderer(image_size=args.size, anti_aliasing=False, camera_mode="look_at")
    textures = jnp.broadcast_to(jnp.array([1., 1., 0.]), (1, len(faces), 3))
    lit = renderer.lighting(world, indices, textures)
    # Keep perspective division, lighting, soft coverage and image aggregation on host.
    rasterize = jax.jit(lambda camera: renderer.rasterize(
        renderer.perspective_distortion(camera, renderer.viewing_angle), indices, lit))
    full_forward = jax.jit(lambda eye: renderer.rasterize(
        renderer.perspective_distortion(renderer.look_at(world, eye), renderer.viewing_angle), indices, lit))
    metrics = []
    float_frames, quantized_frames = [], []
    total_batches = 0
    for frame in range(args.frames):
        angle = frame * 360.0 / args.frames
        renderer.set_eye_from_angles(2.0, 30.0, angle)
        rotation = camera_rotation(renderer, jnp, np)
        weights = np.rint(rotation * ROTATION_SCALE).astype(np.int8)
        bias = np.rint(-np.asarray(renderer.eye) @ rotation * vertex_scale * ROTATION_SCALE).astype(np.int32)
        jw, jb = jnp.asarray(weights), jnp.asarray(bias)

        def transform(x):
            return jax.lax.dot_general(x, jw, (((1,), (0,)), ((), ())),
                                       preferred_element_type=jnp.int32) + jb

        padded = np.zeros(((len(inputs) + BATCH - 1) // BATCH * BATCH, 3), dtype=np.int8)
        padded[:len(inputs)] = inputs
        expected = np.asarray(jax.jit(transform)(jnp.asarray(padded)))
        start = time.perf_counter()
        if args.backend == "rtl":
            frame_dir = out / f"frame-{frame:03d}"
            frame_dir.mkdir(exist_ok=True)
            export_function(transform, jnp.asarray(padded[:BATCH]), frame_dir / "transform.json")
            artifact = frame_dir / "transform.t3m"
            subprocess.run([str(args.compiler.resolve()), str(frame_dir / "transform.json"),
                            "-o", str(artifact)], check=True, capture_output=True, text=True)
            results = []
            for batch in padded.reshape(-1, BATCH, 3):
                completed = subprocess.run([str(args.rtl_runner.resolve()), str(artifact)] +
                                           [str(int(v)) for v in batch.reshape(-1)],
                                           check=True, capture_output=True, text=True)
                result = np.asarray([int(v) for v in completed.stdout.split()], dtype=np.int32)
                if result.size != BATCH * 3:
                    raise ValueError("RTL runner returned incorrect output size")
                results.append(result.reshape(BATCH, 3))
            actual = np.concatenate(results)
            if not np.array_equal(actual, expected):
                raise AssertionError(f"RTL/JAX integer mismatch at angle {angle}")
            total_batches += len(results)
            if frame == 0:
                write_fixture(out, artifact.read_bytes(), padded[:BATCH], expected[:BATCH], weights, bias)
        else:
            actual = expected
        transform_seconds = time.perf_counter() - start
        camera_quantized = actual[:len(vertices)].astype(np.float32) / (vertex_scale * ROTATION_SCALE)
        camera_float = np.asarray(renderer.look_at(world, renderer.eye))[0]
        reference = np.asarray(full_forward(renderer.eye))[0].transpose(1, 2, 0)
        rendered = np.asarray(rasterize(jnp.asarray(camera_quantized[None])))[0].transpose(1, 2, 0)
        if not np.isfinite(reference).all() or not np.isfinite(rendered).all():
            raise AssertionError("renderer produced nonfinite pixels")
        a = np.rint(np.clip(reference[..., :3], 0, 1) * 255).astype(np.uint8)
        b = np.rint(np.clip(rendered[..., :3], 0, 1) * 255).astype(np.uint8)
        float_frames.append(a)
        quantized_frames.append(b)
        item = {"azimuth_degrees": angle,
                "camera_max_abs_error": float(np.abs(camera_quantized - camera_float).max()),
                "rgb_mean_abs_error_255": float(np.abs(a.astype(float) - b).mean()),
                "transform_wall_seconds": transform_seconds}
        metrics.append(item)
        print(f"frame {frame + 1}/{args.frames}: angle={angle:g}, "
              f"camera error={item['camera_max_abs_error']:.5f}, "
              f"RGB MAE={item['rgb_mean_abs_error_255']:.3f}", flush=True)
    for name, frames in [("jax-reference", float_frames), (args.backend + "-transform", quantized_frames)]:
        imageio.mimsave(out / f"{name}.gif", frames, duration=250, loop=0)
        imageio.imwrite(out / f"{name}.png", frames[0])
    # Enlarged nearest-neighbor panels: reference | quantized/RTL | amplified difference.
    diff = np.clip(np.abs(float_frames[0].astype(int) - quantized_frames[0].astype(int)) * 4, 0, 255).astype(np.uint8)
    panels = np.concatenate([float_frames[0], quantized_frames[0], diff], axis=1)
    imageio.imwrite(out / "comparison.png", np.repeat(np.repeat(panels, 4, axis=0), 4, axis=1))
    report = {"jaxsim_commit": commit, "backend": args.backend, "size": args.size,
              "original_mesh": original_counts, "reduced_mesh": {"vertices": len(vertices), "faces": len(faces)},
              "batch_size": BATCH, "vertex_scale": vertex_scale, "rotation_scale": ROTATION_SCALE,
              "rtl_verified_batches": total_batches,
              "mesh_storage_bytes": int(inputs.nbytes + faces.size * 2),
              "rgb_frame_bytes": args.size * args.size * 3,
              "scope": "TPU RTL camera transform only; host lighting, perspective and soft rasterization. "
                       "Reduced mesh reference. Wall times are host simulation, not board performance.",
              "frames": metrics}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if args.backend == "rtl":
        shutil.copyfile(Path(__file__).with_name("viewer.html"), out / "viewer.html")
    print(f"Saved renders and report to {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jaxsim", type=Path, required=True, help="checkout at the pinned commit")
    parser.add_argument("--out", type=Path, default=ROOT / "build-banana/render")
    parser.add_argument("--backend", choices=("jax", "rtl"), default="rtl")
    parser.add_argument("--compiler", type=Path, default=ROOT / "build-banana/tiny3tpu-compile")
    parser.add_argument("--rtl-runner", type=Path, default=ROOT / "build-banana/axis-rtl/obj/Vsynapse32_tpu_peripheral")
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--cells", type=int, default=8, help="mesh vertex-clustering grid per axis")
    args = parser.parse_args()
    if min(args.size, args.frames) < 1 or args.cells < 2:
        parser.error("size/frames must be positive and cells at least 2")
    run(args)


if __name__ == "__main__":
    main()
