#!/usr/bin/env python3
"""Keep unowned RX FIFO payload outside the UART reset tree, like TX."""
import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("uart_tx_fifo", HERE.parent / "uart-fifo/prepare.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
ROOT = base.ROOT


def prepare(out):
    path = base.prepare(out)
    text = path.read_text()
    store = "                            rx_fifo[rx_fifo_tail] <= rx_shift;\n"
    assert text.count(store) == 1
    text = text.replace(store, "")
    block = '''// Only head/count-owned entries are observable. Reset clears ownership;
// a coincident payload write may touch an unowned byte, overwritten before use.
always @(posedge clk) begin
    if(rx_state==RX_STOP && rx_baud_counter==0 && rx && !rx_fifo_clear_request &&
       (!rx_fifo_full || rx_fifo_pop_request))
        rx_fifo[rx_fifo_tail] <= rx_shift;
end

'''
    text = text.replace("always @(posedge clk or posedge rst) begin", block + "always @(posedge clk or posedge rst) begin", 1)
    path.write_text(text)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--out", type=Path, required=True)
    print(prepare(parser.parse_args().out.resolve()))
