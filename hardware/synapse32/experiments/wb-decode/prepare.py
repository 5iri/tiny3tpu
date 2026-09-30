"""Decode the next Wishbone address at its existing capture edge."""
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OLD = """    wire ctrl_select=wb_adr[29:14]==16'hf000;
    wire dram_select=wb_adr[29:28]==2'b01;"""
NEW = """    reg ctrl_select, dram_select;
    always @(posedge clk) begin
        if (rst) begin
            ctrl_select <= 1'b0;
            dram_select <= 1'b0;
        end else if (req_valid && req_ready) begin
            ctrl_select <= req_addr[31:16]==16'hf000;
            dram_select <= req_addr[31:30]==2'b01;
        end
    end"""

def patch_top(source):
    assert source.count(OLD) == 1
    return source.replace(OLD, NEW)
