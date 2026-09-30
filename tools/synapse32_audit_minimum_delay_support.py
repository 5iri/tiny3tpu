"""Fail-closed readiness audit: scalar backend delays cannot prove physical hold."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('/tmp/tiny3tpu-nextpnr-current')
OUT = ROOT / 'build-grade2-minimum-delay-audit'
paths = {
    'delay_type': BASE / 'xilinx/archdefs.h',
    'route_model': BASE / 'xilinx/arch.h',
    'cell_model': Path('/tmp/tiny3tpu-nextpnr-lossless-pre-fixup/arch.cc'),
    'exporter': Path('/tmp/tiny3tpu-nextpnr-grade2-guidance/timing.cc'),
    'linked_backend': Path('/tmp/tiny3tpu-nextpnr-placement-label-replay/manifest.json'),
}
source = {key: path.read_text() for key, path in paths.items()}
linked = json.loads(source['linked_backend'])
assert any('grade2-guidance/timing.o' in x for x in linked['link'])
assert any('lossless-pre-fixup/arch.o' in x for x in linked['link'])
checks = {
    'minimum_and_maximum_share_scalar': all(x in source['delay_type'] for x in [
        'delay_t minDelay() const { return delay; }',
        'delay_t maxDelay() const { return delay; }']),
    'cell_lookup_uses_maximum': 'delay.delay = found_delay->max_delay;' in source['cell_model'],
    'route_lookup_uses_maximum': 'pip_timing.max_delay +' in source['route_model'],
    'clock_network_uses_other_board_calibration': all(x in source['route_model'] for x in [
        'VC707', 'GLOBAL_SPINE_HOP = 70', 'GLOBAL_EXIT_HOP = 1697']),
    'export_uses_maximum_cell_and_cq': all(x in source['exporter'] for x in [
        'ctx->getDelayNS(d.maxDelay())', 'ctx->getDelayNS(c.clockToQ.maxDelay())']),
}
assert all(checks.values()), checks
record = {
    'audit_completed': True,
    'physical_hold_analysis_ready': False,
    'clock_skew_validated': False,
    'full_soc_timing_accepted': False,
    'findings': checks,
    'required_work': [
        'Preserve independently qualified minimum and maximum primitive and routed delays.',
        'Qualify KC705 clock insertion and skew, including related gated CPU clock.',
        'Export minimum CQ/data paths and launch/capture clock paths without substituting maxima.',
        'Check hold plus clock uncertainty and reset recovery/removal against actual constraints.',
    ],
    'scope': 'Source and linkage audit only; no computed hold slack or physical violation claim.',
    'sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [*paths.values(), Path(__file__).resolve()]},
}
OUT.mkdir(exist_ok=False)
(OUT / 'report.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({k: v for k, v in record.items() if k != 'sha256'}, indent=2))
