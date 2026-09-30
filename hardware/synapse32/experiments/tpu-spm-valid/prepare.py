"""Use ownership bits for zero-after-reset TPU input scratchpads."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
def patch(source):
    for name,limit in [('t_count','FEED_CYCLES'),('flush_count','FLUSH_CYCLES')]:
        old='    integer '+name+';'
        assert source.count(old)==1
        source=source.replace(old,'    reg [(( $clog2('+limit+') > 0) ? $clog2('+limit+') : 1)-1:0] '+name+';')
    for bank in ['a','b']:
        old=f'    reg signed [DW-1:0] {bank}_spm [0:N-1][0:N-1];'
        assert source.count(old)==1
        source=source.replace(old,f'    wire signed [DW-1:0] {bank}_spm [0:N-1][0:N-1];\n    reg signed [DW-1:0] {bank}_payload [0:N-1][0:N-1];\n    reg [N*N-1:0] {bank}_written;')
        old=f"                    {bank}_spm[i][j] <= {{DW{{1'b0}}}};\n"
        assert source.count(old)==1
        source=source.replace(old,'')
    start=source.index('            if (load_en && !busy) begin')
    end=source.index('            case (state)',start)
    original=source[start:end]
    assert 'a_spm[load_row][load_col] <= load_data;' in original
    assert 'b_spm[load_row][load_col] <= load_data;' in original
    source=source[:start]+source[end:]
    marker='    genvar gi;'
    block="""    // Payload may be uninitialized; ownership supplies architectural zero.
    genvar vr, vc;
    generate for (vr=0; vr<N; vr=vr+1) begin : VALID_ROW
        for (vc=0; vc<N; vc=vc+1) begin : VALID_COL
            assign a_spm[vr][vc] = a_written[vr*N+vc] ? a_payload[vr][vc] : {DW{1'b0}};
            assign b_spm[vr][vc] = b_written[vr*N+vc] ? b_payload[vr][vc] : {DW{1'b0}};
        end
    end endgenerate
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            a_written <= {N*N{1'b0}};
            b_written <= {N*N{1'b0}};
        end else if (load_en && !busy) begin
            if (load_sel) b_written[load_row*N+load_col] <= 1'b1;
            else a_written[load_row*N+load_col] <= 1'b1;
        end
    end
    always @(posedge clk) begin
        if (load_en && !busy) begin
            if (load_sel) b_payload[load_row][load_col] <= load_data;
            else a_payload[load_row][load_col] <= load_data;
        end
    end

"""
    assert source.count(marker)==1
    return source.replace(marker,block+marker)

def prepare(out):
    path=Path(out)/'tpu_core_wrapper.sv'
    path.write_text(patch((ROOT/'multi-core/tpu_core_wrapper.sv').read_text()))
    return path
