#!/usr/bin/env python3
"""Keep empty FIFO payload outside the UART control reset tree."""
import argparse
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def prepare(out):
    out.mkdir(parents=True,exist_ok=True)
    original=(ROOT.parent/"synapse32/rtl/core_modules/uart.v").read_text()
    store="                            tx_fifo[tx_fifo_tail] <= write_data[7:0];\n"
    assert original.count(store)==1
    source=original.replace(store,"")
    block='''// FIFO payload is meaningful only in entries covered by head/count.
// Reset clears that ownership. A payload write during reset is harmless and
// removing reset from this enable avoids routing it through all FIFO data bits.
always @(posedge clk) begin
    if(write_enable && uart_valid && reg_sel==3'd0 && !dlab && fifo_enabled && !tx_fifo_full)
        tx_fifo[tx_fifo_tail] <= write_data[7:0];
end

'''
    source=source.replace("always @(posedge clk or posedge rst) begin",block+"always @(posedge clk or posedge rst) begin",1)
    (out/"uart.v").write_text(source)
    (out/"uart_reference.v").write_text(original.replace("module uart (","module uart_reference ("))
    return out/"uart.v"


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path,required=True)
    print(prepare(parser.parse_args().out.resolve()))
