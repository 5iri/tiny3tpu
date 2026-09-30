"""Compile StableHLO text/portable bytecode: python -m tools.program."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from . import ProgramError, CPU, KC705, KC705_ROCKET, CompileOptions, compile_stablehlo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    parser.add_argument('--target', choices=('cpu', 'kc705', 'kc705-rocket'), default='cpu')
    parser.add_argument('--symbol', default='t3p')
    parser.add_argument('--entry', default='main')
    parser.add_argument('--math-mode', choices=('libm', 'freestanding'), default='libm')
    parser.add_argument('--allow-approximation', action='store_true')
    parser.add_argument('--affine-offload', action='store_true')
    parser.add_argument('--affine-policy',choices=('auto','force'),default='auto')
    parser.add_argument('--no-fusion',action='store_true')
    parser.add_argument('--input-fraction-bits', type=int, default=20)
    parser.add_argument('--digits', type=int, default=3)
    parser.add_argument('--coefficient-tolerance', type=float, default=0.)
    parser.add_argument('--workspace-limit', type=int)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    target = {'cpu':CPU,'kc705':KC705,'kc705-rocket':KC705_ROCKET}[args.target]
    if args.workspace_limit is not None:
        target = replace(target, workspace_limit_bytes=args.workspace_limit)
    try:
        report = compile_stablehlo(args.input, args.output, CompileOptions(
            target=target, symbol=args.symbol, math_mode=args.math_mode,
            allow_approximation=args.allow_approximation, affine_offload=args.affine_offload,
            input_fraction_bits=args.input_fraction_bits, digits=args.digits,
            coefficient_tolerance=args.coefficient_tolerance,affine_policy=args.affine_policy,
            fusion=not args.no_fusion), entry=args.entry)
    except ProgramError as exc:
        parser.exit(1, f'compile error: {exc}\n')
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
