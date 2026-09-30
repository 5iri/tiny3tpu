"""Use narrow counters and constant feed-slot decoding for TPU inputs."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
def patch(source):
    for name,limit in [('t_count','FEED_CYCLES'),('flush_count','FLUSH_CYCLES')]:
        old='    integer '+name+';'
        assert source.count(old)==1
        source=source.replace(old,'    reg [(( $clog2('+limit+') > 0) ? $clog2('+limit+') : 1)-1:0] '+name+';')
    start=source.index('                    for (i = 0; i < N; i++) begin',source.index('                ST_FEED: begin'))
    end=source.index('                    if (t_count == (FEED_CYCLES - 1))',start)
    source=source[:start]+"""                    for (i = 0; i < N; i++) begin
                        a_in[i] <= {DW{1'b0}};
                        b_in[i] <= {DW{1'b0}};
                        for (j = 0; j < N; j++) begin
                            if (t_count == (i+j)) begin
                                a_in[i] <= a_spm[i][j];
                                b_in[i] <= b_spm[j][i];
                            end
                        end
                    end

"""+source[end:]
    source=source.replace('    integer k;\n','')
    return source

def prepare(out):
    path=Path(out)/'tpu_core_wrapper.sv'
    path.write_text(patch((ROOT/'multi-core/tpu_core_wrapper.sv').read_text()))
    return path
