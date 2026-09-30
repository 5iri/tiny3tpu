"""Exercise the board's 32-to-512 converter, including same-line dependencies."""
import random
import unittest
from migen import run_simulation, passive
from test.test_adapter import ConverterDUT
from test.common import timeout_generator


class Width512Test(unittest.TestCase):
    strict_write_schedule = False

    def test_masked_write_read_and_bursts(self):
        for latency in (0,3):
            with self.subTest(read_backpressure=latency):
                dut=ConverterDUT(user_data_width=32,native_data_width=512,
                                 mem_depth=128,separate_rw=False,read_latency=latency)
                rng=random.Random(0x32dd512)
                reference=[0]*2048

                @passive
                def ordered_memory():
                    # One ordered native port. Independent upstream read/write
                    # handlers can let a read overtake an earlier write when
                    # their delays differ; that model is unsuitable for RAW.
                    port=dut.write_crossbar_port
                    delay=random.Random(0x512)
                    while True:
                        yield port.cmd.ready.eq(1)
                        yield
                        while not (yield port.cmd.valid):yield
                        adr=(yield port.cmd.addr);writing=(yield port.cmd.we)
                        yield port.cmd.ready.eq(0)
                        # A real native DDR controller does not wait for
                        # wdata.valid. Its chosen write phase consumes data.
                        wait = 4 if writing and self.strict_write_schedule else delay.randrange(8)
                        for _ in range(wait):yield
                        if writing:
                            yield port.wdata.ready.eq(1)
                            yield
                            if self.strict_write_schedule:
                                self.assertTrue((yield port.wdata.valid),
                                    f"native write data missing at scheduled phase adr={adr}")
                            else:
                                while not (yield port.wdata.valid):yield
                            dut.memory._write(adr,(yield port.wdata.data),(yield port.wdata.we))
                            yield port.wdata.ready.eq(0)
                        else:
                            yield port.rdata.data.eq(dut.memory._read(adr))
                            yield port.rdata.valid.eq(1)
                            yield
                            while not (yield port.rdata.ready):yield
                            yield port.rdata.valid.eq(0)
                        yield

                def write(adr,data,mask,last):
                    yield from dut.write(adr,data,we=mask,last=last)
                    for byte in range(4):
                        if mask & (1<<byte):
                            reference[adr]=(reference[adr] & ~(255<<(8*byte))) | (data & (255<<(8*byte)))

                def main():
                    # Consecutive commands straddle 512-bit words and 4 KiB.
                    for adr in range(1007,1040):
                        yield from write(adr,rng.getrandbits(32),rng.randrange(16),adr==1039)
                    for adr in range(1007,1040):
                        got=yield from dut.read(adr,last=1)
                        self.assertEqual(got,reference[adr],f"burst adr={adr}")
                    # An immediately following read must observe masked writes
                    # to the same word, even while the wide write is draining.
                    for i in range(64):
                        adr=rng.randrange(1008,1040)
                        yield from write(adr,rng.getrandbits(32),i%16,i%3==0)
                        got=yield from dut.read(adr,last=1)
                        self.assertEqual(got,reference[adr],f"dependent i={i} adr={adr} mask={i%16} got={got:08x} expected={reference[adr]:08x}")
                    yield from dut.write_driver.wait_all()
                    for _ in range(80):yield

                run_simulation(dut,[main(),*dut.driver_generators,ordered_memory(),timeout_generator(20000)])
                expected=[sum(reference[base+i]<<(i*32) for i in range(16)) for base in range(0,2048,16)]
                self.assertEqual(dut.memory.mem,expected)


class StrictNativeWriteTest(Width512Test):
    strict_write_schedule = True
