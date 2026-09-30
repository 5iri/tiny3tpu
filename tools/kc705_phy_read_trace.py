"""Diagnostic capture of sixteen DFI cycles after a software READ command."""
from functools import reduce
from operator import or_

from migen import Array, Cat, If, Memory, Module, Signal
from litex.soc.interconnect.csr import AutoCSR, CSR, CSRStatus, CSRStorage


class ReadTrace(Module, AutoCSR):
    def __init__(self, data, read_enable, read_valid):
        assert len(data) == 64
        self.arm = CSR(name="arm")
        self.index = CSRStorage(4, name="index")
        self.data = CSRStatus(64, name="data")
        self.valid = CSRStatus(16, name="valid")
        self.done = CSRStatus(name="done")
        armed, busy = Signal(), Signal()
        index = Signal(4)
        trigger = Signal()
        history = Memory(64, 16)
        wr = history.get_port(write_capable=True)
        rd = history.get_port(async_read=True)
        self.specials += history, wr, rd
        self.comb += [trigger.eq(armed & read_enable),
                      wr.adr.eq(index), wr.dat_w.eq(data), wr.we.eq(busy | trigger),
                      rd.adr.eq(self.index.storage), self.data.status.eq(rd.dat_r)]
        self.sync += [
            If(self.arm.re,
                armed.eq(1), busy.eq(0), index.eq(0), self.done.status.eq(0),
                self.valid.status.eq(0)
            ).Elif(busy | trigger,
                Array(self.valid.status)[index].eq(read_valid),
                armed.eq(0), index.eq(index + 1),
                If(index == 15, busy.eq(0), self.done.status.eq(1)).Else(busy.eq(1))
            )
        ]


def attach_read_trace(phy):
    phases = phy.dfi.phases
    assert len(phases) == 4 and len(phases[0].rddata) == 128
    # Each byte is one lane's eight chronological samples on its prime DQ.
    data = Cat(*(phases[n//2].rddata[(n%2)*64 + 8*lane]
                 for lane in range(8) for n in range(8)))
    phy.submodules.trace = ReadTrace(data,
        reduce(or_, (p.rddata_en for p in phases)), phases[0].rddata_valid)
