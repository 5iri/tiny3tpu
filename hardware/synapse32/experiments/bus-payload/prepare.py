#!/usr/bin/env python3
"""Capture request payload without routing alignment checks into data enables."""
import argparse
import importlib.util
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("registered_bus",HERE.parent/"registered-bus/prepare.py")
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


def prepare(out):
    path=base.prepare(out);source=path.read_text()
    start=source.index("                    ST_SETTLE: begin")
    end=source.index("                    ST_DATA_REQ: begin",start)
    block=source[start:end]
    block,count=re.subn(r"^\s*request_(?:write|addr|wdata|wstrb) <= [^;]+;\n","\n",block,flags=re.M)
    assert count==12,count
    capture='''
                        // The control below still validates every request.
                        // Payload is unobservable if validation faults, so its
                        // enables need only the state, not the alignment path.
                        request_write <= cpu_wr_en && !cpu_rd_en;
                        request_addr <= cpu_rd_en ? {cpu_rd_addr[31:2],2'b00} :
                                        cpu_wr_en ? {cpu_wr_addr[31:2],2'b00} : cpu_pc;
                        request_wdata <= cpu_wr_en ? cpu_wdata << (cpu_wr_addr[1:0]*8) : 32'b0;
                        request_wstrb <= cpu_wr_en ? cpu_wstrb << cpu_wr_addr[1:0] : 4'b0;
'''
    block=block.replace("ST_SETTLE: begin", "ST_SETTLE: begin"+capture,1)
    path.write_text(source[:start]+block+source[end:])
    return path


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    print(prepare(parser.parse_args().out.resolve()))
