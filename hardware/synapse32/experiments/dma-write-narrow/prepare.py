"""Bound the burst byte-count datapath without narrowing wrapping beat counters."""
from pathlib import Path
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[3] / 'third_party/verilog-axi/rtl/axi_dma_wr.v'
OLD = "reg [LEN_WIDTH-1:0] tr_word_count_reg = {LEN_WIDTH{1'b0}}, tr_word_count_next;"
NEW = """// This profile transfers at most 64 bytes per AXI burst, including page splits.
localparam TR_WORD_WIDTH = (!ENABLE_UNALIGNED && LEN_WIDTH == 16 &&
    AXI_ADDR_WIDTH == 32 && AXI_MAX_BURST_SIZE == 64 && OFFSET_MASK == 3) ? 7 : LEN_WIDTH;
reg [TR_WORD_WIDTH-1:0] tr_word_count_reg = {TR_WORD_WIDTH{1'b0}}, tr_word_count_next;"""

def patch(source):
    assert source.count(OLD) == 1
    result = source.replace(OLD, NEW)
    assert result.replace(NEW, OLD) == source
    return result

def prepare(out):
    (Path(out) / 'axi_dma_wr.v').write_text(patch(SOURCE.read_text()))
