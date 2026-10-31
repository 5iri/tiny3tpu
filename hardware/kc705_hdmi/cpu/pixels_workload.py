"""Small compiler/CPU/TPU/framebuffer fixture, independent of the mesh renderer."""
import jax
import jax.numpy as jnp


def transform(phase):
    vertices = jnp.array([[-24,-24], [24,-24], [24,24], [-24,24],
                         [-12,-12], [12,-12], [12,12], [-12,12]], jnp.int8)
    angle = phase[0].astype(jnp.float32)*jnp.float32(0.125)
    c, s = jnp.cos(angle), jnp.sin(angle)
    weights = (jnp.stack((jnp.stack((c,-s)), jnp.stack((s,c))))*64).astype(jnp.int8)
    return jax.lax.dot_general(vertices, weights, (((1,),(0,)),((),())),
                               preferred_element_type=jnp.int32)
