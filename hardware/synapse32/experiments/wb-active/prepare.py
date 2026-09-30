"""Capture per-target Wishbone transaction enables at the existing request edge."""
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
NEW = """    reg ctrl_active, dram_active;
    always @(posedge clk) begin
        if (rst) begin
            ctrl_active <= 1'b0;
            dram_active <= 1'b0;
        end else if (req_valid && req_ready) begin
            ctrl_active <= req_addr[31:16]==16'hf000;
            dram_active <= req_addr[31:30]==2'b01;
        end else if (wb_cyc && (wb_ack || wb_err)) begin
            ctrl_active <= 1'b0;
            dram_active <= 1'b0;
        end
    end"""

def patch_top(source):
    anchor="    wire ctrl_select=wb_adr[29:14]==16'hf000;"
    assert source.count(anchor)==1
    source=source.replace(anchor,NEW+'\n'+anchor)
    for target in ('ctrl','dram'):
        for signal in ('wb_cyc','wb_stb'):
            old=f'{signal} && {target}_select'
            assert source.count(old)==1
            source=source.replace(old,f'{target}_active')
    return source
