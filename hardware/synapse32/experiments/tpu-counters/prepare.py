"""Size TPU feed/flush counters for their exact reachable ranges."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
def patch(source):
    for name,limit in [('t_count','FEED_CYCLES'),('flush_count','FLUSH_CYCLES')]:
        old='    integer '+name+';'
        assert source.count(old)==1
        source=source.replace(old,'    reg [(( $clog2('+limit+') > 0) ? $clog2('+limit+') : 1)-1:0] '+name+';')
    return source

def prepare(out):
    path=Path(out)/'tpu_core_wrapper.sv'
    path.write_text(patch((ROOT/'multi-core/tpu_core_wrapper.sv').read_text()))
    return path
