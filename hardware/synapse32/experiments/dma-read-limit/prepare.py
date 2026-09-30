"""Factor current-profile burst/page capacity before comparing remaining bytes."""
from pathlib import Path
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[3] / 'build-dma-read-compare/axi_dma_rd.v'
DECL = "reg [LEN_WIDTH-1:0] tr_word_count_reg = {LEN_WIDTH{1'b0}}, tr_word_count_next;"
CAPACITY = """// Within the last 64-byte page block, the page remainder is the
// tighter limit. Everywhere else, only the AXI burst limit applies.
localparam SHORT_BURST_PROFILE = !ENABLE_UNALIGNED && LEN_WIDTH == 16 &&
    AXI_ADDR_WIDTH == 32 && AXI_MAX_BURST_SIZE == 64 && OFFSET_MASK == 3;
localparam TR_WORD_WIDTH = SHORT_BURST_PROFILE ? 7 : LEN_WIDTH;
wire [5:0] burst_page_offset = addr_reg;
wire [5:0] burst_page_block = addr_reg >> 6;
wire [1:0] burst_lane_offset = addr_reg;
wire [6:0] burst_capacity = 7'd64 - ((burst_page_block == 6'h3f) ?
    {1'b0, burst_page_offset} : {5'b0, burst_lane_offset});
reg [TR_WORD_WIDTH-1:0] tr_word_count_reg = {TR_WORD_WIDTH{1'b0}}, tr_word_count_next;"""
DIRECT = """            if (SHORT_BURST_PROFILE) begin
                tr_word_count_next = op_word_count_reg <= burst_capacity ?
                    op_word_count_reg : burst_capacity;
            end else begin
"""

def burst_body(source):
    begin = source.index('            if (op_word_count_reg <= AXI_MAX_BURST_SIZE')
    end = source.index('                m_axi_araddr_next =', begin)
    return source[begin:end]

def patch(source):
    old = burst_body(source)
    new = DIRECT + old + '            end\n\n'
    assert source.count(DECL) == 1 and source.count(old) == 1
    result = source.replace(DECL, CAPACITY).replace(old, new)
    assert result.replace(CAPACITY, DECL).replace(new, old) == source
    return result

def prepare(out):
    (Path(out) / 'axi_dma_rd.v').write_text(patch(SOURCE.read_text()))
