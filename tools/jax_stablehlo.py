"""Optional JAX frontend: export portable StableHLO for the system compiler."""
from pathlib import Path


def export_function(function, *examples, output=None):
    import jax
    from jax import export
    exported = export.export(jax.jit(function))(*examples)
    artifact = exported.mlir_module_serialized
    if output is not None:
        Path(output).write_bytes(artifact)
    return artifact
