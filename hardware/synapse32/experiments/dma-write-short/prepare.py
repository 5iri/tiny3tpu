"""Derive the first write-beat terminal flag directly from descriptor inputs."""
from pathlib import Path
OLD='                output_last_cycle_next = tr_word_count_next != 0 && tr_word_count_next <= 4;'
EXPR='''(op_word_count_reg != 0) &&
                    (((op_word_count_reg[15:3] == 0) &&
                      (!op_word_count_reg[2] || op_word_count_reg[1:0] == 0)) ||
                     (addr_reg[11:2] == 10'h3ff))'''
NEW='''                output_last_cycle_next = (AXI_ADDR_WIDTH == 32 && AXI_MAX_BURST_SIZE == 64 && OFFSET_MASK == 3) ?
                    '''+EXPR+''' :
                    (tr_word_count_next != 0 && tr_word_count_next <= 4);'''


def patch(source):
    assert source.count(OLD)==1
    assert 'if (!ENABLE_UNALIGNED && LEN_WIDTH == 16 && AXI_BURST_SIZE == 2 && CYCLE_COUNT_WIDTH == 15)' in source
    candidate=source.replace(OLD,NEW)
    assert candidate.replace(NEW,OLD)==source
    return candidate


def prepare(out):
    p=Path(out)/'axi_dma_wr.v';p.write_text(patch(p.read_text()))
