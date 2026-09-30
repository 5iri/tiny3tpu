"""Remove decrement arithmetic from DMA write last-cycle flags."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[3]/'third_party/verilog-axi/rtl/axi_dma_wr.v'
START_OLD='''            output_last_cycle_next = output_cycle_count_next == 0;
            last_transfer_next = tr_word_count_next == op_word_count_reg;'''
START_NEW='''            // For the current aligned 32-bit engine, one output beat means
            // 1..4 bytes. Preserve zero-length underflow and all other profiles.
            if (!ENABLE_UNALIGNED && LEN_WIDTH == 16 && AXI_BURST_SIZE == 2 && CYCLE_COUNT_WIDTH == 15)
                output_last_cycle_next = tr_word_count_next != 0 && tr_word_count_next <= 4;
            else
                output_last_cycle_next = output_cycle_count_next == 0;
            last_transfer_next = tr_word_count_next == op_word_count_reg;'''
STEP_OLD='''                output_cycle_count_next = output_cycle_count_reg - 1;
                output_last_cycle_next = output_cycle_count_next == 0;'''
STEP_NEW='''                output_cycle_count_next = output_cycle_count_reg - 1;
                output_last_cycle_next = output_cycle_count_reg == 1;'''


def patch(source):
    assert source.count(START_OLD)==1 and source.count(STEP_OLD)==2
    assert 'output_cycle_count_next = (tr_word_count_next - 1) >> AXI_BURST_SIZE;' in source
    assert 'reg [CYCLE_COUNT_WIDTH-1:0] output_cycle_count_reg' in source
    result=source.replace(START_OLD,START_NEW).replace(STEP_OLD,STEP_NEW)
    assert result.replace(START_NEW,START_OLD).replace(STEP_NEW,STEP_OLD)==source
    return result


def prepare(out):
    (Path(out)/'axi_dma_wr.v').write_text(patch(SOURCE.read_text()))
