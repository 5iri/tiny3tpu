#!/usr/bin/env python3
"""Express UART FIFO events directly, outside reset-controlled temporaries."""
import argparse
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("uart_rx_fifo", HERE.parent / "uart-rx-fifo/prepare.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
ROOT = base.ROOT


def prepare(out):
    path = base.prepare(out)
    source = path.read_text()
    events = {
        "tx_fifo_pushed": "write_enable && uart_valid && reg_sel==3'd0 && !dlab && fifo_enabled && !tx_fifo_full",
        "tx_fifo_popped": "baud_counter==0 && !tx_fifo_empty && ((tx_state==TX_IDLE && !tx_start_pending) || tx_state==TX_STOP)",
        "tx_fifo_cleared": "write_enable && uart_valid && reg_sel==3'd2 && write_data[2]",
        "rx_fifo_pushed": "rx_state==RX_STOP && rx_baud_counter==0 && rx && !rx_fifo_clear_request && (!rx_fifo_full || rx_fifo_pop_request)",
        "rx_fifo_popped": "rx_fifo_pop_request",
        "rx_fifo_cleared": "rx_fifo_clear_request",
    }
    for name, expression in events.items():
        source, count = re.subn(r"reg\s+" + name + r";", "wire " + name + ";", source)
        assert count == 1, name
        source, count = re.subn(r"^\s*" + name + r"\s*=\s*1'b[01];\n", "", source, flags=re.M)
        assert count >= 2, name
    marker = "// LSR: bit6=TEMT"
    definitions = "// FIFO events are combinational requests. Reset belongs to owned state,\n// not to temporary flags used to compute its next value.\n"
    definitions += "\n".join("assign " + name + " = " + expression + ";" for name, expression in events.items()) + "\n\n"
    assert marker in source
    path.write_text(source.replace(marker, definitions + marker, 1))
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    print(prepare(parser.parse_args().out.resolve()))
