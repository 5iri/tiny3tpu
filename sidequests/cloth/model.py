"""Live adaptation of upstream demo_cloth.py using its dflex force kernels."""
import math
import jax
import jax.numpy as jnp
import numpy as np
from jaxsim import dflex as df
from jaxsim.dflex import sim

class Cloth:
    def __init__(self, nx=12, ny=6):
        self.dt=1/7680
        b=df.sim.ModelBuilder()
        b.add_cloth_grid(pos=(-1.,1.5,0.),rot=df.quat_from_axis_angle((1.,0.,0.),math.pi*1.04),
                         vel=(1.,0.,0.),dim_x=nx,dim_y=ny,cell_x=2/nx,cell_y=1/ny,mass=1.)
        for i,d in ((0,-1.),(nx,1.)):
            anchor=b.add_particle(pos=np.array(b.particle_x[i])+[d,0,0],vel=(0,0,0),mass=0.)
            b.add_spring(anchor,i,10000.,1000.,0)
        m=b.finalize('cpu');m.tri_lambda=10000.;m.tri_ka=10000.;m.tri_kd=100.
        m.ground=False
        m.particle_inv_mass=jnp.linspace(.1,1.,m.particle_count).at[-2:].set(0.)
        self.model=m
        self.count=(nx+1)*(ny+1);self.faces=np.asarray(m.tri_indices)
        self.initial=(m.particle_q,m.particle_v) if hasattr(m,'particle_q') else (m.state().q,m.state().u)
        self.anchors=np.asarray(self.initial[0][-2:])
        def step(pair):
            q,v=pair
            f=sim.eval_springs(q,v,m.spring_indices,m.spring_rest_length,m.spring_stiffness,m.spring_damping)
            f+=sim.eval_triangles(q,v,m.tri_indices,m.tri_poses,m.tri_activations,
                                 m.tri_ke,m.tri_ka,m.tri_kd,m.tri_drag,m.tri_lift)
            f+=sim.eval_bending(q,v,m.edge_indices,m.edge_rest_angle,m.edge_ke,m.edge_kd)
            return sim.integrate_particles(q,v,f,m.particle_inv_mass,m.gravity,self.dt)
        self.advance=jax.jit(lambda pair,n:jax.lax.fori_loop(0,n,lambda _,p:step(p),pair))
        self.advance(self.initial,32)[0].block_until_ready()
