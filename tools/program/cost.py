"""Explicit target cost estimates for optional approximate affine placement.

Cycles are estimates, not timing guarantees. The KC705 transport coefficient is
calibrated against the packed-driver RTL measurement (2.89M cycles for two
162x3x2 calls); CPU and conversion costs are conservative starting estimates.
Targets may override these coefficients without changing the frontend/pass.
"""
from dataclasses import dataclass
import math
from .mmio_codegen import tile_statistics


@dataclass(frozen=True)
class GemmCostModel:
    """VexRiscv + packed mailbox estimates, calibrated with full-SoC RTL.

    CPU MAC cost includes loads and loop control. Transport is per accelerator
    register, including the mailbox envelope, not a bare AXI clock count.
    Auto placement requires a margin; callers can force either exact backend.
    No sparsity or particular application/weight values are assumed.
    """
    name: str = 'vexriscv-mailbox-retained-v1'
    cpu_mac_cycles: float = 52.
    cpu_output_cycles: float = 12.
    register_cycles: float = 800.
    tile_packing_cycles: float = 1200.
    minimum_speedup: float = 1.15

    def __post_init__(self):
        if not all(math.isfinite(v) and v >= 0 for v in
                   (self.cpu_mac_cycles, self.cpu_output_cycles,
                    self.register_cycles, self.tile_packing_cycles)):
            raise ValueError('GEMM cost coefficients must be finite and nonnegative')
        if not math.isfinite(self.minimum_speedup) or self.minimum_speedup < 1:
            raise ValueError('minimum_speedup must be finite and at least one')

    def estimate(self, m, k, n):
        ceil = lambda x, y: (x+y-1)//y
        schedules = (
            ('rows', ceil(m,8)*ceil(k,4)*ceil(n,4)),
            ('k', ceil(m,4)*ceil(k,8)*ceil(n,4)),
            ('columns', ceil(m,4)*ceil(k,4)*ceil(n,8)),
        )
        schedule, launches = min(schedules, key=lambda item:item[1])
        # Full tile estimate; read only the final retained partials. Short-K
        # row batches reuse B; column batches similarly reuse A when M<=4.
        operand_words = 16*launches
        if schedule == 'rows' and k <= 4:
            operand_words = 8*launches+8*ceil(n,4)
        elif schedule == 'columns' and k <= 4 and m <= 4:
            operand_words = 8*launches+8
        results = m*n*(2 if schedule == 'k' and k > 4 else 1)
        transactions = 1+operand_words+2*launches+results
        cpu = m*k*n*self.cpu_mac_cycles+m*n*self.cpu_output_cycles
        tpu = transactions*self.register_cycles+launches*self.tile_packing_cycles
        return dict(model=self.name, cpu_cycles=cpu, tpu_cycles=tpu,
                    schedule=schedule, launches=launches,
                    minimum_speedup=self.minimum_speedup,
                    profitable=tpu*self.minimum_speedup < cpu)


@dataclass(frozen=True)
class SpecializedGemmCostModel(GemmCostModel):
    """Conservative direct-MMIO kernel estimate from full VexRiscv RTL runs.

    Charge all operand words for dynamic packing, even when prepacked constants
    make the actual kernel cheaper. Keep the generic model as a separate target
    property so disabling specialization also restores its placement estimate.
    """
    name: str = 'vexriscv-direct-specialized-v1'
    register_cycles: float = 52.
    tile_packing_cycles: float = 0.
    word_packing_cycles: float = 20.
    launch_cycles: float = 40.
    result_store_cycles: float = 10.

    def __post_init__(self):
        super().__post_init__()
        if not all(math.isfinite(v) and v>=0 for v in
                   (self.word_packing_cycles,self.launch_cycles,self.result_store_cycles)):
            raise ValueError('GEMM cost coefficients must be finite and nonnegative')

    def estimate(self,m,k,n):
        traffic=tile_statistics(m,k,n)
        cpu=m*k*n*self.cpu_mac_cycles+m*n*self.cpu_output_cycles
        tpu=(traffic['register_transactions_min']*self.register_cycles+
             traffic['operand_word_writes']*self.word_packing_cycles+
             traffic['launches']*self.launch_cycles+
             traffic['result_reads']*self.result_store_cycles)
        return dict(model=self.name,cpu_cycles=cpu,tpu_cycles=tpu,**traffic,
                    minimum_speedup=self.minimum_speedup,
                    profitable=tpu*self.minimum_speedup<cpu)


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
        # Retained accumulation and direct result window: read final sums once.
        # One initial status read, packed rows, launch and completion poll.
        # Only K<=4 can
        # retain the complete B tile across all row batches.
        weights=8*math.ceil(n/4) if k<=4 else 8*launches
        results=m*n*(1 if row_parallel or k<=4 else 2)
        return (1+8*launches+weights+2*launches+results)*self.register_cycles

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
