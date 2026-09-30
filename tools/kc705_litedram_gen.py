#!/usr/bin/env python3
"""Generate LiteDRAM with a cycle-equivalent local bank-ready expression.

The stock chooser selects cmd.valid = valids[grant], then feeds cmd.valid back
to every bank's ready output. For bank i, grant == i already selects valids[i].
Using that local bit removes the cross-bank validity mux from the ready path.
No register, command queue, timer, or ready/valid cycle is changed.
The installed LiteDRAM package is never modified.
"""
import hashlib
import inspect
import runpy
import sys
from pathlib import Path

import litedram.core.multiplexer as multiplexer


def install_local_ready(command_ready=False):
    original = multiplexer._CommandChooser
    source = inspect.getsource(original)
    expected = "9ab571c50a2c71e7634a6ef21f5f285157184d7d7aca3ec7ee3f7736c174f387"
    if hashlib.sha256(source.encode()).hexdigest() != expected:
        raise RuntimeError("LiteDRAM chooser source differs from the proven 2024.12 version")
    old = "If(cmd.valid & cmd.ready & (arbiter.grant == i),"
    new = "If(valids[i] & cmd.ready & (arbiter.grant == i),"
    if source.count(old) != 1:
        raise RuntimeError("LiteDRAM chooser changed; review and re-prove the local-ready transformation")
    patched = source.replace(old, new)
    if command_ready:
        patched = patched.replace("def __init__(self, requests):",
                                  "def __init__(self, requests, local_ras_allowed=None):")
        marker = "self.cmd = cmd = stream.Endpoint(cmd_request_rw_layout(a, ba))"
        patched = patched.replace(marker, marker + "\n        self.ready_enable = Signal()")
        marker = "for i, request in enumerate(requests):\n            self.comb +="
        assert patched.count(marker) == 1
        patched = patched.replace(marker,
            "for i, request in enumerate(requests):\n"
            "            local_ready = cmd.ready\n"
            "            if local_ras_allowed is not None:\n"
            "                local_ready = self.ready_enable & (~(request.ras & ~request.cas & ~request.we) | local_ras_allowed)\n"
            "            self.comb +=")
        patched = patched.replace(new, "If(valids[i] & local_ready & (arbiter.grant == i),")
    namespace = dict(vars(multiplexer))
    exec(compile(patched, str(Path(__file__).resolve()), "exec"), namespace)
    multiplexer._CommandChooser = namespace["_CommandChooser"]
    return original, multiplexer._CommandChooser, {
        "original_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "patched_sha256": hashlib.sha256(patched.encode()).hexdigest(),
        "transformation": "bank[i].ready = valids[i] & cmd.ready & (grant == i)",
    }


def install_local_command_ready():
    """Factor the selected-command ACT/RAS check into each bank's ready path.

    Only the four-phase KC705 generator uses this transformation. The shared
    cmd.ready stays unchanged for timing counters and command steering.
    """
    _, _, provenance = install_local_ready(command_ready=True)
    source = inspect.getsource(multiplexer.Multiplexer)
    expected = "464da4fe5b4ff544f7fc33ae45e9ef7dfc7d4b2bc495e8b6817507591f42e5f9"
    if hashlib.sha256(source.encode()).hexdigest() != expected:
        raise RuntimeError("LiteDRAM multiplexer differs from the proven 2024.12 version")
    old = "self.submodules.choose_cmd = choose_cmd = _CommandChooser(requests)"
    assert source.count(old) == 1
    patched = source.replace(old, old[:-1] + ", local_ras_allowed=ras_allowed)")
    old = 'assert(settings.phy.nphases == len(dfi.phases))'
    patched = patched.replace(old, old + '\n        assert settings.phy.nphases == 4')
    old = '        if settings.with_bandwidth:'
    assert patched.count(old) == 1
    patched = patched.replace(old,
        '        self.comb += choose_cmd.ready_enable.eq(fsm.ongoing("READ") | fsm.ongoing("WRITE"))\n\n' + old)
    namespace = dict(vars(multiplexer))
    exec(compile(patched, str(Path(__file__).resolve()), "exec"), namespace)
    multiplexer.Multiplexer = namespace["Multiplexer"]
    import litedram.core.controller as controller
    controller.Multiplexer = multiplexer.Multiplexer
    provenance.update(multiplexer_original_sha256=expected,
                      multiplexer_patched_sha256=hashlib.sha256(patched.encode()).hexdigest(),
                      local_command_ready=True)
    return provenance


if __name__ == "__main__":
    provenance = install_local_command_ready()
    print("KC705 LiteDRAM local-ready transformation:", provenance, flush=True)
    sys.argv[0] = "litedram.gen"
    runpy.run_module("litedram.gen", run_name="__main__")
