"""Fixed-step RK4 integration of SRA-VJTI/jaxsim's DoublePendulum ODE."""
import math
import jax
import jax.numpy as jnp
from jaxsim.bodies import DoublePendulum

class Physics:
    def __init__(self, dt=1/240):
        self.dt=dt
        self.body=DoublePendulum(1.,1.,1.,1.,9.81)
        self.initial=jnp.array([3*math.pi/7,0.,3*math.pi/4,0.],dtype=jnp.float32)
        def one(y):
            f=lambda state:self.body.forward(0.,state)
            k1=f(y);k2=f(y+dt*k1/2);k3=f(y+dt*k2/2);k4=f(y+dt*k3)
            return y+dt*(k1+2*k2+2*k3+k4)/6
        self.advance=jax.jit(lambda y,steps:jax.lax.fori_loop(0,steps,lambda _,state:one(state),y))
        self.energy=jax.jit(self.body.compute_energy)
        self.initial_energy=float(self.energy(self.initial))
        self.advance(self.initial,1).block_until_ready()
    def positions(self,y):
        t1,t2=y[0],y[2]
        p1=jnp.array([jnp.sin(t1),-jnp.cos(t1),0.])
        return jnp.stack([p1,p1+jnp.array([jnp.sin(t2),-jnp.cos(t2),0.])])
