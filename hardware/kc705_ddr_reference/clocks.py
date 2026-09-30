"""nextpnr pre-pack timing overlay for the pinned upstream reference.

The reference PLL is 200 MHz * 5 / {8, 2, 5}. Explicitly constrain its
internal clock nets because the input XDC alone did not propagate through
IBUFDS/PLL/BUFG in the locally installed openXC7 build.
"""
for net, mhz in (
    ("main_crg_clkin", 200),
    ("main_crg_clkout0", 125),
    ("main_crg_clkout_buf0", 125),
    ("main_crg_clkout1", 500),
    ("main_crg_clkout_buf1", 500),
    ("main_crg_clkout2", 200),
    ("idelay_clk", 200),
):
    ctx.addClock(net, mhz)
