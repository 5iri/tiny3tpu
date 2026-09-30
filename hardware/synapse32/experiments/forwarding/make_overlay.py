#!/usr/bin/env python3
"""Materialize a fresh builder-compatible four-file overlay inside this experiment."""
import hashlib
import json
from pathlib import Path
import tempfile

here = Path(__file__).resolve().parent
files = {name: (here if name == 'execution_unit.v' else here.parent / 'divider') / name
         for name in ('riscv_cpu.v', 'execution_unit.v', 'alu.v', 'divider.v')}
# Fail closed if any input has changed since the recorded proof/test handoff.
snapshots = {}
for name, path in files.items():
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    for mode in ('prove', 'test', 'synth'):
        evidence = json.loads((here / 'evidence' / (mode + '.json')).read_text())
        if digest != evidence['sources_sha256'][str(path)]:
            raise ValueError(f'Changed since {mode}: {path}')
    snapshots[name] = (payload, digest)
overlay = Path(tempfile.mkdtemp(prefix='overlay.', dir=here))
manifest = {}
for name, source in files.items():
    payload, digest = snapshots[name]
    (overlay / name).write_bytes(payload)
    if hashlib.sha256((overlay / name).read_bytes()).hexdigest() != digest:
        raise ValueError(f'Overlay copy integrity failure: {name}')
    manifest[name] = dict(source=str(source), sha256=digest)
(overlay / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(overlay)
