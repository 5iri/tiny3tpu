#!/usr/bin/env python3
"""Generate separate CPU and DDR clock outputs with a 100 MHz CPU."""
import sys
import hashlib
import inspect
import json
from migen import ClockDomain
from litex.build.generic_platform import Pins
import litedram.gen as generator
from kc705_litedram_gen import install_local_command_ready


class KC705ClockDomains(generator.LiteDRAMS7DDRPHYCRG):
    def __init__(self, platform, core_config):
        super().__init__(platform, core_config)
        assert core_config["cpu_clk_freq"] in (50e6, 62.5e6, 100e6)
        assert any(abs(core_config["sys_clk_freq"] - f) < 1 for f in (1e9/12, 100e6))
        self.cd_cpu = ClockDomain("cpu")
        self.pll.create_clkout(self.cd_cpu, core_config["cpu_clk_freq"])
        platform.add_extension([("user_cpu_clk", 0, Pins(1)), ("user_cpu_rst", 0, Pins(1))])
        self.comb += [platform.request("user_cpu_clk").eq(self.cd_cpu.clk),
                      platform.request("user_cpu_rst").eq(self.cd_cpu.rst)]


if __name__ == "__main__":
    # An explicit PHY experiment, kept separate from the cycle-equivalent
    # controller factoring. It changes both the PHY valid pulse and the
    # controller's expected read latency by the same number of cycles.
    with open(sys.argv[1]) as config_file:
        config = json.load(config_file)
    offset = config.get("read_latency_offset", 0)
    if config.get("debug_phy_only", False):
        import litedram.core as core
        from litedram.phy.dfi import Interface
        from litedram.dfii import DFIInjector
        class PhyOnlyInjector(DFIInjector):
            def __init__(self, addressbits, bankbits, nranks, databits,
                         nphases=1, is_clam_shell=False):
                super().__init__(addressbits, bankbits, nranks, databits,
                                 nphases, is_clam_shell)
                # Keep hardware-selection idle without resetting the DIMM.
                # The controller connects to a separate unused interface.
                for phase in self.slave.phases:
                    self.comb += [phase.reset_n.eq((1<<nranks)-1),
                                  phase.cke.eq((1<<nranks)-1),
                                  phase.odt.eq((1<<nranks)-1)]
                self.slave = Interface(addressbits, bankbits, nranks, databits, nphases)
        core.DFIInjector = PhyOnlyInjector
        print("DIAGNOSTIC ONLY: native DDR controller disconnected", flush=True)
    trace = config.get("debug_read_trace", False)
    if offset or trace:
        import litedram.phy.s7ddrphy as phy
        source = inspect.getsource(phy.S7DDRPHY)
        before = "read_latency              = cl_sys_latency + 6,"
        assert offset in (-2, -1, 0, 1) and source.count(before) == 1
        patched = source.replace(before, "read_latency              = cl_sys_latency + {},".format(6+offset))
        namespace = dict(vars(phy))
        if trace:
            from kc705_phy_read_trace import attach_read_trace
            namespace["attach_read_trace"] = attach_read_trace
            marker = "        # Write Control Path "
            assert patched.count(marker) == 1
            patched = patched.replace(marker, "        attach_read_trace(self)\n\n" + marker)
        exec(compile(patched, __file__, "exec"), namespace)
        phy.S7DDRPHY = namespace["S7DDRPHY"]
        print("Diagnostic PHY read latency offset:", offset,
              "original SHA256:", hashlib.sha256(source.encode()).hexdigest(), flush=True)
        print("Diagnostic DFI read history:", trace, flush=True)
    print("KC705 LiteDRAM local-ready transformation:", install_local_command_ready(), flush=True)
    generator.LiteDRAMS7DDRPHYCRG = KC705ClockDomains
    sys.argv[0] = "litedram.gen"
    generator.main()
