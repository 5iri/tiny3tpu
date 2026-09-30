#!/usr/bin/env python3
"""Remove the sequencer's request-output mux without adding a bus cycle."""
import argparse
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def once(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new)


def prepare(out):
    out.mkdir(parents=True,exist_ok=True)
    seq=(ROOT/"hardware/synapse32/synapse32_memory_sequencer.sv").read_text()
    seq=once(seq,"req_write = (state == ST_FETCH_REQ) ? 1'b0 : request_write;","req_write = request_write;")
    seq=once(seq,"req_addr = (state == ST_FETCH_REQ) ? fetch_addr : request_addr;","req_addr = request_addr;")
    seq=once(seq,"req_wdata = (state == ST_FETCH_REQ) ? 32'b0 : request_wdata;","req_wdata = request_wdata;")
    seq=once(seq,"req_wstrb = (state == ST_FETCH_REQ) ? 4'b0 : request_wstrb;","req_wstrb = request_wstrb;")
    seq=once(seq,"request_addr      <= 32'b0;","request_addr      <= RESET_PC;")
    seq=once(seq,"""                            fetch_addr <= cpu_pc;
                            state <= ST_FETCH_REQ;""","""                            fetch_addr <= cpu_pc;
                            request_addr <= cpu_pc;
                            request_write <= 1'b0;
                            request_wdata <= 32'b0;
                            request_wstrb <= 4'b0;
                            state <= ST_FETCH_REQ;""")
    seq=once(seq,"""                                                               load_type_latched);
                                state <= ST_FETCH_REQ;""","""                                                               load_type_latched);
                                // Switch to the already saved fetch request on
                                // the response edge, before asserting req_valid.
                                request_addr <= fetch_addr;
                                request_write <= 1'b0;
                                request_wdata <= 32'b0;
                                request_wstrb <= 4'b0;
                                state <= ST_FETCH_REQ;""")
    (out/"synapse32_memory_sequencer.sv").write_text(seq)
    return out/"synapse32_memory_sequencer.sv"


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    print(prepare(args.out.resolve()))
