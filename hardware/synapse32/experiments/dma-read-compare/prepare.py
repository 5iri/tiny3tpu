"""Eliminate subtraction from the DMA read descriptor-ready decision."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[3]/'third_party/verilog-axi/rtl/axi_dma_rd.v'
OLD='                if (op_word_count_next > 0) begin'
NEW='                if (op_word_count_reg != tr_word_count_next) begin'

def patch(source):
    assert source.count(OLD)==1
    assert source.count('                op_word_count_next = op_word_count_reg - tr_word_count_next;')==1
    assert source.index('                op_word_count_next = op_word_count_reg - tr_word_count_next;')<source.index(OLD)
    # Both arithmetic operands and the stored difference have the same
    # unsigned width. Subtraction modulo 2**LEN_WIDTH is zero exactly on equality.
    assert 'reg [LEN_WIDTH-1:0] op_word_count_reg' in source
    assert 'reg [LEN_WIDTH-1:0] tr_word_count_reg' in source
    return source.replace(OLD,NEW)

def prepare(out):
    (Path(out)/'axi_dma_rd.v').write_text(patch(SOURCE.read_text()))
