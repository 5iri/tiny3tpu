"""UART transport and bounded latency accounting for live board viewers."""
from collections import deque
import math


def open_transport(port, *, baudrate=921600, stop=None):
    import serial
    return serial.Serial(port, baudrate, timeout=.1, write_timeout=1)


class LatencyWindow:
    """Bounded rolling latency percentiles; overhead includes firmware and host."""
    def __init__(self, size=256):
        if size < 1: raise ValueError('Latency window must be positive')
        self.samples = deque(maxlen=size)

    def observe(self, roundtrip_ms, compute_ms):
        if not all(math.isfinite(v) and v >= 0 for v in (roundtrip_ms, compute_ms)):
            raise ValueError('Latency samples must be finite and nonnegative')
        self.samples.append((roundtrip_ms, compute_ms, max(0., roundtrip_ms - compute_ms)))

    def summary(self):
        def stats(values):
            values = sorted(values)
            def percentile(q):
                position = (len(values)-1)*q; low = int(position); high = min(low+1, len(values)-1)
                return values[low] + (values[high]-values[low])*(position-low)
            return dict(p50=percentile(.5), p95=percentile(.95), p99=percentile(.99))
        return dict(samples=len(self.samples), **({name:stats(row[index] for row in self.samples)
            for index, name in enumerate(('roundtrip_ms','compute_ms','outside_compute_ms'))} if self.samples else {}))
