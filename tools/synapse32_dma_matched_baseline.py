#!/usr/bin/env python3
"""Run the DMA workload using the hash-verified original wrapper in isolation."""
import hashlib
import importlib.util
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
original = root / "build-dma-descriptor-end-register-baseline-rtl/synapse32_axi_dma.sv"
assert hashlib.sha256(original.read_bytes()).hexdigest() == (
    "a98fd52962aec6958b6f867ba0c07314f78f37c0a6d431babad113f4510ce8c8"
)
experiment = root / "hardware/synapse32/experiments/dma"
sys.path.insert(0, str(experiment))
spec = importlib.util.spec_from_file_location("dma_run_matched_baseline", experiment / "run.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rtl = module.rtl


def baseline_rtl(*args, **kwargs):
    sources = rtl(*args, **kwargs)
    matches = [i for i, path in enumerate(sources) if path.name == "synapse32_axi_dma.sv"]
    assert len(matches) == 1
    sources[matches[0]] = original
    return sources


module.rtl = baseline_rtl
module.main()
