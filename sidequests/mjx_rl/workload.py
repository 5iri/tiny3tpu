"""MuJoCo MJX upright pendulum and a completely staged policy-search learner.

The first learner uses antithetic random search (return-based policy updates),
not simulator gradients. Physics always calls mjx.step. This keeps the initial
on-device training proof small enough to audit before adding an actor-critic.
"""
import jax
import jax.numpy as jnp
import mujoco
from mujoco import mjx
import numpy as np

XML = '''<mujoco model="tiny3tpu-pendulum">
  <option timestep="0.02" jacobian="sparse">
    <flag contact="disable" eulerdamp="disable"/>
  </option>
  <worldbody><body>
    <joint name="hinge" type="hinge" axis="0 1 0" damping="0.02"/>
    <geom type="capsule" fromto="0 0 0 0 0 1" size=".04" mass="1"/>
  </body></worldbody>
  <actuator><motor joint="hinge"/></actuator>
</mujoco>'''


def make_physics():
    model = mujoco.MjModel.from_xml_string(XML)
    device_model = mjx.put_model(model, impl='jax')
    template = mjx.make_data(device_model)
    def physics(state, action):
        # No contacts, stateful actuators, applied forces or warm-started
        # constraints in this model: qpos/qvel are its full recurrent state.
        data = template.replace(qpos=state[:1], qvel=state[1:2], ctrl=jnp.reshape(action,(1,)))
        data = mjx.step(device_model,data)
        return jnp.concatenate((data.qpos,data.qvel))
    return model,physics


def policy(weights, state):
    # Explicit quantization: float master weights remain trainable, while this
    # inference product can run on the existing exact INT8 -> INT32 TPU.
    features=jnp.stack((jnp.sin(state[0]),state[1]*jnp.float32(.25)))
    x=(jnp.clip(features,-1.9,1.9)*64).astype(jnp.int8).reshape(1,2)
    w=(jnp.clip(weights,-15.,15.)*8).astype(jnp.int8).reshape(2,1)
    product=jax.lax.dot_general(x,w,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
    return jnp.clip(product[0,0].astype(jnp.float32)/512.,-2.,2.)


def make_learner(horizon=128, directions=4):
    if horizon<1 or directions<1:
        raise ValueError('horizon and directions must be positive')
    model,physics=make_physics()
    def rollout(weights, angle, steps=None):
        def body(_,carry):
            state,total=carry
            action=policy(weights,state)
            state=physics(state,action)
            reward=jnp.cos(state[0])-jnp.float32(.01)*state[1]*state[1]-jnp.float32(.001)*action*action
            return state,total+reward
        steps=horizon if steps is None else steps
        return jax.lax.fori_loop(0,steps,body,(jnp.array([angle,0.],jnp.float32),jnp.float32(0)))[1]/steps

    def random(seed):
        # Small reproducible, fully resident PRNG. The 24-bit carry is exactly
        # representable in the packed f32 state; arithmetic explicitly wraps.
        seed=(seed*jnp.uint32(1664525)+jnp.uint32(1013904223))&jnp.uint32(0xffffff)
        return seed,seed.astype(jnp.float32)*jnp.float32(1./8388608.)-1.

    def update(state):
        weights=state[:2]
        seed=state[2].astype(jnp.uint32)
        steps=state[4].astype(jnp.int32)
        count=state[5].astype(jnp.int32)
        def candidate(_,carry):
            seed,gradient,sums,squares=carry
            seed,a=random(seed);seed,b=random(seed)
            direction=jnp.stack((a,b))
            positive=rollout(weights+direction*2.,jnp.float32(.15),steps)
            negative=rollout(weights-direction*2.,jnp.float32(.15),steps)
            return (seed,gradient+(positive-negative)*direction,
                    sums+positive+negative,squares+positive*positive+negative*negative)
        seed,gradient,sums,squares=jax.lax.fori_loop(0,count,candidate,
            (seed,jnp.zeros(2,jnp.float32),jnp.float32(0),jnp.float32(0)))
        mean=sums/(2*count)
        deviation=jnp.sqrt(jnp.maximum(squares/(2*count)-mean*mean,1e-6))
        weights=jnp.clip(weights+(jnp.float32(.35)/count)*gradient/deviation,-15.,15.)
        return jnp.concatenate((weights,jnp.reshape(seed.astype(jnp.float32),(1,)),
                                jnp.reshape(state[3]+1.,(1,)),state[4:]))

    def train(state, iterations):
        return jax.lax.fori_loop(0,iterations,lambda _,s:update(s),state)
    return model,physics,rollout,update,train


def initial_state(seed=1,horizon=128,directions=4):
    if not 0<=seed<2**24:raise ValueError('seed must fit 24 bits')
    if not 1<=horizon<=4096 or not 1<=directions<=128:raise ValueError('invalid rollout limits')
    return np.array([0.,0.,seed,0.,horizon,directions],np.float32)


def make_tick():
    """One resident training/simulation tick, so firmware can render between ticks.

    State: weights[2], rng, updates, horizon, directions, q, v, step, side,
    direction index, return sum, positive return, perturbation[2], gradient[2],
    return sum across candidates, squared returns, last update's mean return.
    """
    _,physics=make_physics()
    def tick(s):
        fresh=(s[8]==0)&(s[9]==0)
        seed=s[2].astype(jnp.uint32)
        seed1=(seed*jnp.uint32(1664525)+jnp.uint32(1013904223))&jnp.uint32(0xffffff)
        seed2=(seed1*jnp.uint32(1664525)+jnp.uint32(1013904223))&jnp.uint32(0xffffff)
        random_direction=jnp.stack((seed1,seed2)).astype(jnp.float32)*jnp.float32(1./8388608.)-1.
        direction=jnp.where(fresh,random_direction,s[13:15])
        action=policy(s[:2]+jnp.where(s[9]==0,2.,-2.)*direction,s[6:8])
        qv=physics(s[6:8],action)
        reward=jnp.cos(qv[0])-jnp.float32(.01)*qv[1]*qv[1]-jnp.float32(.001)*action*action
        total=s[11]+reward
        score=total/s[4]
        finish=s[8]+1>=s[4]
        negative=finish&(s[9]!=0)
        completed=negative&(s[10]+1>=s[5])
        gradient=s[15:17]+(s[12]-score)*direction
        sums=s[17]+s[12]+score
        squares=s[18]+s[12]*s[12]+score*score
        mean=sums/(2*s[5])
        deviation=jnp.sqrt(jnp.maximum(squares/(2*s[5])-mean*mean,1e-6))
        weights=jnp.clip(s[:2]+(jnp.float32(.35)/s[5])*gradient/deviation,-15.,15.)
        return jnp.concatenate((
            jnp.where(completed,weights,s[:2]),
            jnp.stack((jnp.where(fresh,seed2.astype(jnp.float32),s[2]),
                       s[3]+completed.astype(jnp.float32),s[4],s[5])),
            jnp.where(finish,jnp.array([.15,0.],jnp.float32),qv),
            jnp.stack((jnp.where(finish,0.,s[8]+1),jnp.where(finish,1.-s[9],s[9]),
                       jnp.where(negative,jnp.where(completed,0.,s[10]+1),s[10]),
                       jnp.where(finish,0.,total),jnp.where(finish&(s[9]==0),score,s[12]))),
            direction,jnp.where(completed,jnp.zeros(2,jnp.float32),jnp.where(negative,gradient,s[15:17])),
            jnp.stack((jnp.where(completed,0.,jnp.where(negative,sums,s[17])),
                       jnp.where(completed,0.,jnp.where(negative,squares,s[18])),
                       jnp.where(completed,mean,s[19])))))
    return tick


def initial_tick_state(seed=1,horizon=128,directions=4):
    result=np.zeros(20,np.float32)
    result[:6]=initial_state(seed,horizon,directions)
    result[6]=.15
    return result
