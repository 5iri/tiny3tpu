"""BananaSpinner369: live JAX rotation with an exact INT8 vertex GEMM.

The mesh in hardware/kc705_hdmi/assets/mesh.json is resident program data. No animated
vertices or frames are stored. Generated RV32 code computes the rotation and
dispatches the GEMM through the two-core 4x4 TPU backend.
"""
import json
from pathlib import Path
import jax
import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[3]


def make_workload():
    mesh=json.loads((ROOT/'hardware/kc705_hdmi/assets/mesh.json').read_text())
    vertices=jnp.asarray(mesh['vertices'],dtype=jnp.int8)
    ce=jnp.float32(np.cos(np.deg2rad(20)))
    se=jnp.float32(np.sin(np.deg2rad(20)))

    def banana_spinner369(phase):
        angle=phase[0].astype(jnp.float32)*jnp.float32(2*np.pi/256)
        c,s=jnp.cos(angle),jnp.sin(angle)
        matrix=jnp.stack((jnp.stack((c,s*se,-s*ce)),
                          jnp.stack((jnp.float32(0),ce,se)),
                          jnp.stack((s,-c*se,c*ce))))*jnp.float32(127)
        weights=jnp.where(matrix<0,matrix-jnp.float32(.5),matrix+jnp.float32(.5)).astype(jnp.int8)
        return jax.lax.dot_general(vertices,weights,(((1,),(0,)),((),())),
                                   preferred_element_type=jnp.int32)
    return banana_spinner369
