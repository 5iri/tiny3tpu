"""Export actual MJX kinematics for the renderer's live geom transforms."""
import jax.numpy as jnp
from mujoco import mjx
from workload import make_physics

def make_pose():
    model,_=make_physics()
    mx=mjx.put_model(model,impl='jax');template=mjx.make_data(mx)
    def pose(qpos):
        d=mjx.kinematics(mx,template.replace(qpos=qpos))
        return jnp.concatenate((d.geom_xpos,d.geom_xmat.reshape(model.ngeom,9)),axis=1).ravel()
    return pose
