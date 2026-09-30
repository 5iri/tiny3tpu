"""Explicit target cost estimates for optional approximate affine placement.

Cycles are estimates, not timing guarantees. The KC705 transport coefficient is
calibrated against the packed-driver RTL measurement (2.89M cycles for two
162x3x2 calls); CPU and conversion costs are conservative starting estimates.
Targets may override these coefficients without changing the frontend/pass.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class AffineCostModel:
    name: str = 'kc705-packed-mailbox-v1'
    register_cycles: float = 950.
    float_add_cycles: float = 350.
    float_mul_cycles: float = 350.
    float_neg_cycles: float = 40.
    pack_input_cycles: float = 1100.
    unpack_output_cycles: float = 600.
    minimum_speedup: float = 1.15

    def __post_init__(self):
        values=(self.register_cycles,self.float_add_cycles,self.float_mul_cycles,
                self.float_neg_cycles,self.pack_input_cycles,self.unpack_output_cycles)
        if not all(math.isfinite(x) and x>=0 for x in values):
            raise ValueError('cost coefficients must be finite and nonnegative')
        if not math.isfinite(self.minimum_speedup) or self.minimum_speedup<1:
            raise ValueError('minimum_speedup must be finite and at least one')

    def gemm_cycles(self,m,k,n):
        row_tiles=math.ceil(m/8)*math.ceil(k/4)
        k_tiles=math.ceil(m/4)*math.ceil(k/8)
        row_parallel=row_tiles<=k_tiles
        launches=min(row_tiles,k_tiles)*math.ceil(n/4)
        # One initial status read, packed A/B rows, launch + completion poll,
        # and four transactions for each useful core result. Only K<=4 can
        # retain the complete B tile across all row batches.
        weights=8*math.ceil(n/4) if k<=4 else 8*launches
        results=m*n*(math.ceil(k/4) if row_parallel else math.ceil(k/8)+k//8+(k%8>4))
        return (1+8*launches+weights+2*launches+4*results)*self.register_cycles

    def estimate(self,plan,outputs,roots,params):
        # Find work actually eliminated. Shared intermediates retained by a
        # different consumer must not be charged as CPU savings.
        needed=set(plan.outputs);removed=[]
        candidates=set().union(*(params['source_nodes'][o] for o in outputs))
        for node in reversed(plan.nodes):
            if node.output in needed:
                if node.output in outputs:needed.update(roots);removed.append(node)
                else:needed.update(node.inputs)
            elif node.output in candidates:removed.append(node)
        prices={'add':self.float_add_cycles,'add_any':self.float_add_cycles,
                'sub':self.float_add_cycles,'mul':self.float_mul_cycles,'neg':self.float_neg_cycles}
        cpu=sum(plan.values[n.output].size*prices.get(n.op,0.) for n in removed)
        rows=plan.values[outputs[0]].size;cols=len(outputs);k=len(roots)
        transport=sum(self.gemm_cycles(len(g['rows'])*params['digits'],k,cols) for g in params['groups'])
        conversion=rows*(k*self.pack_input_cycles+cols*self.unpack_output_cycles)
        total=transport+conversion
        return dict(model=self.name,cpu_cycles=cpu,tpu_cycles=total,
                    transport_cycles=transport,conversion_cycles=conversion,
                    minimum_speedup=self.minimum_speedup,
                    profitable=total*self.minimum_speedup<cpu)
