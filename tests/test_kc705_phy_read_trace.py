"""Check diagnostic history trigger, sample order, valid mask and rearming."""
import sys
from pathlib import Path

from migen import Signal
from migen.sim import run_simulation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from kc705_phy_read_trace import ReadTrace


def main():
    data, enable, valid = Signal(64), Signal(), Signal()
    dut = ReadTrace(data, enable, valid)

    def stimulus():
        for base in (0x0123456700000000, 0xfedcba9800000000):
            yield dut.arm.re.eq(1)
            yield
            yield dut.arm.re.eq(0)
            yield
            yield enable.eq(1)
            for i in range(16):
                yield data.eq(base + i)
                yield valid.eq(i in (6, 7))
                if i:
                    yield enable.eq(0)
                yield
            yield
            assert (yield dut.done.status) == 1
            assert (yield dut.valid.status) == 0xc0
            # Further commands cannot overwrite a completed, unarmed trace.
            yield enable.eq(1)
            yield data.eq(0xffffffffffffffff)
            yield
            yield enable.eq(0)
            yield
            for i in range(16):
                yield dut.index.storage.eq(i)
                yield
                yield
                actual = yield dut.data.status
                assert actual == base+i, (i, hex(actual), hex(base+i))

    run_simulation(dut, stimulus())
    print("PASS read history: two captures, 16 ordered samples, valid mask, freeze and rearm")


if __name__ == "__main__":
    main()
