`timescale 1ns/1ps
// Board builds use a dedicated glitch-free global clock-enable buffer.
// The simulation model accepts CE throughout the low phase and holds it
// during the high phase (UG472 BUFGCE behavior). No fabric clock gating.
module synapse32_clock_enable (
    input wire clk, input wire enable, output wire cpu_clk
);
`ifdef SYNAPSE32_CLOCK_SIM
    reg enabled=0;
    always @* if (!clk) enabled <= enable;
    assign cpu_clk = clk && enabled;
`else
    BUFGCE cpu_global_clock (.I(clk), .CE(enable), .O(cpu_clk));
`endif
endmodule
