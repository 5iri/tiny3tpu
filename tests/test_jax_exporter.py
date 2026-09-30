#!/usr/bin/env python3
"""Focused JAX exporter tests (exit 77 is an honest JAX skip)."""
import json, subprocess, sys, tempfile
from pathlib import Path

try:
    import jax
    import jax.numpy as jnp
except ImportError:
    print("SKIP: JAX is not installed")
    raise SystemExit(77)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.jax_export import ExportError, export_function

W = jnp.array([[2, -1, 3], [-2, 4, 1]], dtype=jnp.int8)
B = jnp.array([17, -23, 5], dtype=jnp.int32)
X = jnp.array([[3, -4], [-5, 6]], dtype=jnp.int8)

def dot(x):
    return jax.lax.dot_general(x, W, (((1,), (0,)), ((), ())), preferred_element_type=jnp.int32)

def exported(model):
    with tempfile.TemporaryDirectory(prefix="tiny3tpu-jax-") as d:
        path = Path(d) / "model.json"
        graph = export_function(model, X, path)
        return graph, json.loads(path.read_text(encoding="utf-8"))

def compiled_output(model, compiler, input_values, runner=None):
    with tempfile.TemporaryDirectory(prefix="tiny3tpu-jax-compile-") as d:
        json_path = Path(d) / "model.json"
        artifact_path = Path(d) / "model.t3m"
        export_function(model, X, json_path)
        result = subprocess.run(
            [str(compiler), str(json_path), "-o", str(artifact_path),
             "--run-input", ",".join(str(int(v)) for v in input_values)],
            text=True, capture_output=True, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        line = next((line for line in result.stdout.splitlines()
                     if line.startswith("reference output:")), "")
        assert line, result.stdout
        reference = [int(value) for value in line.split(":", 1)[1].split()]
        if runner is not None:
            executed = subprocess.run(
                [str(runner), str(artifact_path)] + [str(int(v)) for v in input_values],
                text=True, capture_output=True, check=False,
            )
            assert executed.returncode == 0, executed.stdout + executed.stderr
            assert [int(v) for v in executed.stdout.split()] == reference
        return reference

def expect_error(model, message):
    try:
        exported(model)
    except ExportError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError("unsupported graph was exported")

def main():
    if len(sys.argv) not in (2, 3):
        raise AssertionError("CTest must pass the tiny3tpu-compile executable path")
    compiler = Path(sys.argv[1])
    runner = Path(sys.argv[2]) if len(sys.argv) == 3 else None
    assert compiler.is_file() and compiler.stat().st_mode & 0o111, compiler
    _, graph = exported(dot)
    assert graph["tensors"][1]["shape"] == [3, 2]
    assert graph["tensors"][0]["flags"] == ["input"]
    assert graph["tensors"][3]["dtype"] == "i32" and graph["tensors"][3]["flags"] == ["output"]
    expected = [int(v) for v in jax.device_get(dot(X)).reshape(-1)]
    assert compiled_output(dot, compiler, X.reshape(-1), runner) == expected
    biased = lambda x: dot(x) + B
    _, graph = exported(biased)
    assert graph["tensors"][2]["data"] == B.tolist()
    biased_expected = [int(v) for v in jax.device_get(biased(X)).reshape(-1)]
    assert compiled_output(biased, compiler, X.reshape(-1), runner) == biased_expected
    expect_error(lambda x: dot(x) + B + B, "exactly one bias fusion")
    expect_error(lambda x: x, "unsupported JAX primitive")
    expect_error(lambda x: jax.lax.dot_general(x, W, (((0,), (0,)), ((), ())), preferred_element_type=jnp.int32), "only rank-2")
    print("JAX exporter focused tests passed")
    return 0

if __name__ == "__main__": raise SystemExit(main())
