"""Common compiler entry point: verify, transform, legalize, plan storage, emit."""
from dataclasses import dataclass
import copy
from ._schedule import ProgramError
from .target import CPU, Target
from .partition import partition_affine
from .c_backend import emit_c
from .optimize import compose_indices


@dataclass(frozen=True)
class CompileOptions:
    target: Target = CPU
    symbol: str = 't3p'
    math_mode: str = 'libm'
    allow_approximation: bool = False
    affine_offload: bool = False
    input_fraction_bits: int = 20
    digits: int = 3
    coefficient_tolerance: float = 0.0
    fusion: bool = True
    affine_policy: str = 'auto'


def _compile_schedule(program, path, options=None):
    options = options or CompileOptions()
    p = copy.deepcopy(program)  # Compiling for another target must not mutate source IR.
    p.validate()
    p.dce()
    composed = compose_indices(p) if options.fusion else 0
    if options.affine_policy not in ('auto','force'):
        raise ProgramError('affine_policy must be auto or force')
    partitions = [];decisions=[]
    if options.affine_offload:
        if not options.allow_approximation:
            raise ProgramError('affine_offload requires explicit allow_approximation')
        if not options.target.qgemm:
            raise ProgramError(f'{options.target.name}: affine_offload requires int8 QGEMM support')
        def partition_regions(plan, region_path='main'):
            records=[];local_decisions=[]
            for node in plan.nodes:
                for index,child in enumerate(node.params.get('regions',[])):
                    records.extend(partition_regions(child,f'{region_path}/while{node.output}/{index}'))
            records.extend(dict(record,region=region_path) for record in partition_affine(
                plan,options.coefficient_tolerance,options.input_fraction_bits,options.digits,
                cost_model=options.target.affine_cost_model,policy=options.affine_policy,decisions=local_decisions))
            decisions.extend(dict(record,region=region_path) for record in local_decisions)
            return records
        partitions = partition_regions(p)
    report = emit_c(p, path, target=options.target, symbol=options.symbol,
                    math_mode=options.math_mode, allow_approximation=options.allow_approximation,
                    fusion=options.fusion)
    report['composed_index_maps'] = composed
    report['affine_placement_decisions'] = decisions
    report.update(target=options.target.describe(), program=p.summary(), partitions=partitions,
                  numerical_policy={
                      'math_mode': options.math_mode,
                      'allow_approximation': options.allow_approximation,
                      'affine_offload': options.affine_offload,
                      'affine_policy': options.affine_policy,
                      'input_fraction_bits': options.input_fraction_bits if partitions else None,
                      'coefficient_tolerance': options.coefficient_tolerance if partitions else None,
                      'float_reassociation': bool(partitions),
                  })
    return report
