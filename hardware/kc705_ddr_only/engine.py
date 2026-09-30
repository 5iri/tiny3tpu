"""CPU-free KC705 DDR3 initialization, bounded PHY training and destructive BIST.

The two Wishbone masters are private wires to LiteDRAM, not a system bus.
All decisions are finite-state hardware; there is no firmware or instruction ROM.
Requires the generated LiteDRAM 2024.12 CSR map (32-bit, big-endian CSR words).
"""
from functools import reduce
from operator import or_

from migen import *
from litex.soc.interconnect import wishbone


class DDR3TestEngine(Module):
    def __init__(self, registers, *, clock_hz=100_000_000, mr0=0x920,
                 mr1=6, mr2=0x200, half_taps=8, window_bursts=4096,
                 timeout_cycles=65536):
        if not 1 <= window_bursts <= 4096:
            raise ValueError("window_bursts must be in 1..4096")
        if not 1 <= half_taps < 32 or timeout_cycles < 8:
            raise ValueError("invalid PHY taps or watchdog")
        self.ctrl = ctrl = wishbone.Interface(data_width=32, adr_width=30)
        self.mem = mem = wishbone.Interface(data_width=512, adr_width=24)
        self.initialized = Signal()
        self.calibrated = Signal()
        self.passed = Signal()
        self.failed = Signal()
        self.busy = Signal()
        # 1=CSR timeout/error, 2=write-leveling, 3=memory timeout/error,
        # 4=no read window, 5=BIST mismatch. A reset is required after failure.
        self.failure_code = Signal(3)
        self.failure_address = Signal(24)  # 64-byte burst address
        self.failure_lanes = Signal(8)
        self.stage = Signal(3)  # 0=init, 1=write level, 2=read scan, 3=BIST, 4=done
        self.best_width = best_width = Array(Signal(6, name=f"eye_width_{i}") for i in range(8))
        self.best_delay = best_delay = Array(Signal(5, name=f"read_tap_{i}") for i in range(8))
        self.best_read_slip = best_rs = Array(Signal(3, name=f"read_slip_{i}") for i in range(8))
        self.best_write_slip = best_ws = Array(Signal(3, name=f"write_slip_{i}") for i in range(8))
        self.write_delay = write_delay = Array(Signal(5, name=f"write_tap_{i}") for i in range(8))
        self.submodules.fsm = fsm = FSM(reset_state="INIT_0")
        self.comb += [self.busy.eq(~(self.passed | self.failed)),
                     ctrl.sel.eq(15), mem.sel.eq((1 << 64)-1)]
        watchdog = Signal(max=timeout_cycles)
        self.sync += If((ctrl.cyc | mem.cyc) & ~(ctrl.ack | ctrl.err | mem.ack | mem.err),
                        If(watchdog != timeout_cycles-1, watchdog.eq(watchdog+1))).Else(watchdog.eq(0))

        def addr(name, word=0):
            reg = registers[name]
            if reg["addr"] % 4 or not 0 <= word < reg["size"]:
                raise ValueError("invalid CSR: " + name)
            return reg["addr"]//4 + word

        def fail(code, lanes=0):
            return [NextValue(self.failed, 1), NextValue(self.failure_code, code),
                    NextValue(self.failure_lanes, lanes),
                    NextValue(self.failure_address, mem.adr), NextState("FAILED")]

        # Every transfer has a full idle cycle afterwards. This is important
        # for pulse CSRs: keeping CYC asserted after ACK can increment twice.
        def csr(state, name, value, next_state, *, read=False, word=0, after=()):
            fsm.act(state, ctrl.cyc.eq(1), ctrl.stb.eq(1), ctrl.we.eq(not read),
                    ctrl.adr.eq(addr(name, word)), ctrl.dat_w.eq(value),
                    If(ctrl.err, *fail(1)).Elif(ctrl.ack, *after, NextState(state+"_GAP"))
                    .Elif(watchdog == timeout_cycles-1, *fail(1)))
            fsm.act(state+"_GAP", NextState(next_state))

        wait_counter = Signal(32)

        def wait(state, cycles, next_state, after=()):
            fsm.act(state, If(wait_counter == cycles-1, NextValue(wait_counter, 0),
                             *after, NextState(next_state))
                    .Else(NextValue(wait_counter, wait_counter+1)))

        def sequence(prefix, operations, next_state):
            for index, operation in enumerate(operations):
                state = f"{prefix}_{index}"
                dest = f"{prefix}_{index+1}" if index+1 < len(operations) else next_state
                if operation[0] == "wait":
                    wait(state, operation[1], dest)
                else:
                    csr(state, operation[0], operation[1], dest)

        def mode(bank, value):
            return [("sdram_dfii_pi0_address", value), ("sdram_dfii_pi0_baddress", bank),
                    ("sdram_dfii_pi0_command", 15), ("sdram_dfii_pi0_command_issue", 1),
                    ("wait", 16)]

        # Explicit reset-low interval is needed even when reprogramming an
        # already powered DIMM. LiteDRAM's cdelay values are not cycle counts.
        sequence("INIT", [
            ("sdram_dfii_control", 0), ("ddrctrl_init_done", 0), ("ddrctrl_init_error", 0),
            ("ddrphy_rst", 1), ("wait", 1024), ("ddrphy_rst", 0),
            ("wait", (clock_hz+4999)//5000),  # reset low >=200 us
            ("sdram_dfii_control", 8), ("wait", (clock_hz+1999)//2000),  # >=500 us
            ("sdram_dfii_control", 14), ("wait", 1024),
        ] + mode(2, mr2) + mode(3, 0) + mode(1, mr1) + mode(0, mr0) + [
            ("wait", 1024), ("sdram_dfii_pi0_address", 0x400),
            ("sdram_dfii_pi0_baddress", 0), ("sdram_dfii_pi0_command", 3),
            ("sdram_dfii_pi0_command_issue", 1), ("wait", 1024),
            ("ddrphy_dly_sel", 255), ("ddrphy_rdly_dq_rst", 1),
            ("ddrphy_rdly_dq_bitslip_rst", 1), ("ddrphy_wdly_dq_bitslip_rst", 1),
        ], "WL_BEGIN")

        tap = Signal(5)
        samples = Signal(3)
        ones = [Signal(4) for _ in range(8)]
        seen_low = Signal(8)
        previous_high = Signal(8)
        found = Signal(8)
        high = Signal(8)
        self.comb += high.eq(Cat(*(count >= 6 for count in ones)))  # 6/8 agreement
        fsm.act("WL_BEGIN", NextValue(self.initialized, 1), NextValue(self.stage, 1), NextState("WL_SETUP_0"))
        sequence("WL_SETUP", mode(1, mr1 | 128) + [
            ("ddrphy_wlevel_en", 1), ("ddrphy_wdly_dq_rst", 1),
            ("ddrphy_wdly_dqs_rst", 1), ("wait", 128)], "WL_STROBE")
        csr("WL_STROBE", "ddrphy_wlevel_strobe", 1, "WL_SETTLE")
        wait("WL_SETTLE", 128, "WL_READ_HI")
        # CSR word zero holds DFI bits 127:96: lanes 4..7 of the second beat.
        for word in range(2):
            lane_base = 4 if word == 0 else 0
            csr("WL_READ_HI" if word == 0 else "WL_READ_LO", "sdram_dfii_pi0_rddata", 0,
                "WL_READ_LO" if word == 0 else "WL_SAMPLE", read=True, word=word,
                after=[NextValue(ones[lane_base+i], ones[lane_base+i]+ctrl.dat_r[8*i]) for i in range(4)])
        fsm.act("WL_SAMPLE", If(samples == 7, NextValue(samples, 0), NextState("WL_TAP"))
                .Else(NextValue(samples, samples+1), NextState("WL_STROBE")))
        fsm.act("WL_TAP", NextValue(seen_low, seen_low | ~high), NextValue(previous_high, high),
                *[If(~found[i] & seen_low[i] & previous_high[i] & high[i],
                     NextValue(write_delay[i], tap-1), NextValue(found[i], 1)) for i in range(8)],
                *[NextValue(count, 0) for count in ones],
                If(tap == 31-half_taps, NextState("WL_CHECK"))
                .Else(NextValue(tap, tap+1), NextState("WL_INC_DQ")))
        csr("WL_INC_DQ", "ddrphy_wdly_dq_inc", 1, "WL_INC_DQS")
        csr("WL_INC_DQS", "ddrphy_wdly_dqs_inc", 1, "WL_STROBE")
        fsm.act("WL_CHECK", If(found != 255, *fail(2, ~found)).Else(NextValue(tap, 0), NextState("WL_OFF_0")))
        sequence("WL_OFF", mode(1, mr1) + [("ddrphy_wlevel_en", 0), ("wait", 128)], "WL_SELECT")
        lane = Signal(3)
        csr("WL_SELECT", "ddrphy_dly_sel", 1 << lane, "WL_RESET_DQ")
        csr("WL_RESET_DQ", "ddrphy_wdly_dq_rst", 1, "WL_RESET_DQS")
        csr("WL_RESET_DQS", "ddrphy_wdly_dqs_rst", 1, "WL_APPLY")
        fsm.act("WL_APPLY", If(tap == write_delay[lane], NextValue(tap, 0),
                    If(lane == 7, NextValue(lane, 0), NextState("SCAN_SETUP_0"))
                    .Else(NextValue(lane, lane+1), NextState("WL_SELECT")))
                .Else(NextValue(tap, tap+1), NextState("WL_APPLY_DQ")))
        csr("WL_APPLY_DQ", "ddrphy_wdly_dq_inc", 1, "WL_APPLY_DQS")
        csr("WL_APPLY_DQS", "ddrphy_wdly_dqs_inc", 1, "WL_APPLY")

        # Normal controller transactions train on every DQ bit, not MPR's DQ0.
        # Scan 8 write slips x 8 read slips x 32 input taps at the generated
        # command/read/write phases. Choose the center of each lane's longest
        # contiguous passing read window; require >=3 taps before proceeding.
        sequence("SCAN_SETUP", [("ddrphy_dly_sel", 255), ("sdram_dfii_control", 1),
                                 ("wait", 128)], "SCAN_BEGIN")
        read_slip = Signal(3)
        write_slip = Signal(3)
        run_width = [Signal(6) for _ in range(8)]
        good = Signal(8, reset=255)
        trial = Signal(3)
        pattern_salt = Signal(32)
        fsm.act("SCAN_BEGIN", NextValue(self.stage, 2), NextValue(good, 255),
                NextValue(pattern_salt, Cat(tap, read_slip, write_slip)),
                NextState("SCAN_WRITE"))

        def pattern(address, salt, inverse):
            # Distinct words and beats reveal burst rotation and lane swaps.
            return Cat(*((address ^ salt ^ Constant(((i+1)*0x9e3779b9) & 0xffffffff, 32))
                         ^ Replicate(inverse, 32) for i in range(16)))

        mismatch = Signal(8)
        expected = Signal(512)
        captured = Signal(512)
        self.comb += mismatch.eq(Cat(*(reduce(or_, (
            captured[beat*64+i*8:beat*64+i*8+8] != expected[beat*64+i*8:beat*64+i*8+8]
            for beat in range(8))) for i in range(8))))

        def memory(state, address, data, write, next_state, select=None):
            extra = [] if select is None else [mem.sel.eq(select)]
            fsm.act(state, mem.cyc.eq(1), mem.stb.eq(1), mem.we.eq(write),
                    mem.adr.eq(address), mem.dat_w.eq(data), *extra,
                    If(mem.err, *fail(3)).Elif(mem.ack, NextValue(captured, mem.dat_r),
                        NextValue(expected, data), NextState(state+"_GAP"))
                    .Elif(watchdog == timeout_cycles-1, *fail(3)))
            fsm.act(state+"_GAP", NextState(next_state))

        training_data = pattern(trial[:2], pattern_salt, trial[2])
        memory("SCAN_WRITE", trial[:2], training_data, 1, "SCAN_READ")
        memory("SCAN_READ", trial[:2], training_data, 0, "SCAN_COMPARE")
        fsm.act("SCAN_COMPARE", NextValue(good, good & ~mismatch),
                If(trial == 7, NextValue(trial, 0), NextState("SCAN_SCORE"))
                .Else(NextValue(trial, trial+1), NextState("SCAN_WRITE")))
        fsm.act("SCAN_SCORE", *[
            If(good[i], NextValue(run_width[i], run_width[i]+1),
               If(run_width[i]+1 > best_width[i], NextValue(best_width[i], run_width[i]+1),
                  NextValue(best_delay[i], tap-(run_width[i] >> 1)),
                  NextValue(best_rs[i], read_slip), NextValue(best_ws[i], write_slip)))
            .Else(NextValue(run_width[i], 0)) for i in range(8)],
            If(tap == 31, NextValue(tap, 0), NextState("SCAN_NEXT_SLIP"))
            .Else(NextValue(tap, tap+1), NextState("SCAN_INC")))
        csr("SCAN_INC", "ddrphy_rdly_dq_inc", 1, "SCAN_BEGIN")
        fsm.act("SCAN_NEXT_SLIP", *[NextValue(width, 0) for width in run_width],
                If(read_slip == 7, NextValue(read_slip, 0),
                    If(write_slip == 7, NextState("SCAN_CHECK"))
                    .Else(NextValue(write_slip, write_slip+1), NextState("SCAN_WSLIP")))
                .Else(NextValue(read_slip, read_slip+1), NextState("SCAN_RSLIP")))
        csr("SCAN_RSLIP", "ddrphy_rdly_dq_bitslip", 1, "SCAN_RESET_TAP")
        csr("SCAN_WSLIP", "ddrphy_wdly_dq_bitslip", 1, "SCAN_RESET_SLIP")
        csr("SCAN_RESET_SLIP", "ddrphy_rdly_dq_bitslip_rst", 1, "SCAN_RESET_TAP")
        csr("SCAN_RESET_TAP", "ddrphy_rdly_dq_rst", 1, "SCAN_BEGIN")
        missing = Cat(*(width < 3 for width in best_width))
        fsm.act("SCAN_CHECK", If(missing != 0, *fail(4, missing)).Else(NextState("APPLY_SELECT")))
        csr("APPLY_SELECT", "ddrphy_dly_sel", 1 << lane, "APPLY_RESET_0")
        sequence("APPLY_RESET", [("ddrphy_rdly_dq_rst", 1), ("ddrphy_rdly_dq_bitslip_rst", 1),
                                 ("ddrphy_wdly_dq_bitslip_rst", 1)], "APPLY_TAP")
        fsm.act("APPLY_TAP", If(tap == best_delay[lane], NextValue(tap, 0), NextState("APPLY_RS"))
                .Else(NextValue(tap, tap+1), NextState("APPLY_TAP_INC")))
        csr("APPLY_TAP_INC", "ddrphy_rdly_dq_inc", 1, "APPLY_TAP")
        fsm.act("APPLY_RS", If(tap == best_rs[lane], NextValue(tap, 0), NextState("APPLY_WS"))
                .Else(NextValue(tap, tap+1), NextState("APPLY_RS_INC")))
        csr("APPLY_RS_INC", "ddrphy_rdly_dq_bitslip", 1, "APPLY_RS")
        fsm.act("APPLY_WS", If(tap == best_ws[lane], NextValue(tap, 0),
                    If(lane == 7, NextState("TRAINED_0"))
                    .Else(NextValue(lane, lane+1), NextState("APPLY_SELECT")))
                .Else(NextValue(tap, tap+1), NextState("APPLY_WS_INC")))
        csr("APPLY_WS_INC", "ddrphy_wdly_dq_bitslip", 1, "APPLY_WS")
        sequence("TRAINED", [("ddrphy_dly_sel", 0), ("ddrctrl_init_done", 1)], "BIST_BEGIN")

        # Address-line probes followed by eight windows spanning the DIMM.
        # Fill the whole set before reading so aliased addresses cannot pass.
        index = Signal(max=8*window_bursts+25)
        burst_address = Signal(24)
        dense_index = Signal(15)
        self.comb += dense_index.eq(index-25)
        if window_bursts & (window_bursts-1):
            raise ValueError("window_bursts must be a power of two")
        shift = (window_bursts-1).bit_length()
        window = dense_index >> shift
        offset = dense_index & (window_bursts-1)
        # Keep probe and window datasets separate: several addresses overlap.
        probes = Signal(reset=1)
        address_bit = Signal(5)
        self.comb += address_bit.eq(index-1)
        self.comb += If(probes, burst_address.eq(Mux(index == 0, 0, Constant(1, 24) << address_bit)))
        # During the window test index starts at 25 to reuse dense_index.
        self.comb += If(~probes, burst_address.eq(Mux(window == 7,
                        (1 << 24)-window_bursts, window << 21) + offset))
        inverse = Signal()
        bist_data = pattern(burst_address, Constant(0x51a7c0de, 32), inverse)
        end_index = Mux(probes, 24, 8*window_bursts+24)
        fsm.act("BIST_BEGIN", NextValue(self.calibrated, 1), NextValue(self.stage, 3), NextState("BIST_WRITE"))
        memory("BIST_WRITE", burst_address, bist_data, 1, "BIST_WRITE_NEXT")
        fsm.act("BIST_WRITE_NEXT", If(index == end_index, NextValue(index, Mux(probes, 0, 25)),
                                     NextState("BIST_READ"))
                .Else(NextValue(index, index+1), NextState("BIST_WRITE")))
        memory("BIST_READ", burst_address, bist_data, 0, "BIST_COMPARE")
        fsm.act("BIST_COMPARE", If(mismatch != 0, *fail(5, mismatch),
                                   NextValue(self.failure_address, burst_address))
                .Elif(index == end_index,
                    NextValue(index, Mux(probes, 0, 25)),
                    If(~inverse, NextValue(inverse, 1), NextState("BIST_WRITE"))
                    .Elif(probes, NextValue(probes, 0), NextValue(index, 25),
                          NextValue(inverse, 0), NextState("BIST_WRITE"))
                    .Else(NextState("MASK_CLEAR")))
                .Else(NextValue(index, index+1), NextState("BIST_READ")))

        byte = Signal(6, name_override="byte_index")
        mask_expected = Signal(512)
        next_mask_expected = Signal(512)
        byte_bit_offset = Cat(Constant(0, 3), byte)
        self.comb += next_mask_expected.eq(mask_expected | ((byte+Constant(1, 8)) << byte_bit_offset))
        memory("MASK_CLEAR", 0, 0, 1, "MASK_WRITE")
        # Non-selected bytes carry ones, so broken byte enables are visible.
        mask_payload = Cat(*(Mux(byte == i, i+1, 255) for i in range(64)))
        memory("MASK_WRITE", 0, mask_payload, 1, "MASK_UPDATE", select=Constant(1, 64) << byte)
        fsm.act("MASK_UPDATE", NextValue(mask_expected, next_mask_expected), NextState("MASK_READ"))
        memory("MASK_READ", 0, mask_expected, 0, "MASK_COMPARE")
        fsm.act("MASK_COMPARE", If(mismatch != 0, *fail(5, mismatch))
                .Elif(byte == 63, NextValue(self.passed, 1), NextValue(self.stage, 4), NextState("PASSED"))
                .Else(NextValue(byte, byte+1), NextState("MASK_WRITE")))
        fsm.act("PASSED", NextState("PASSED"))
        # Sticky terminal failure; no more memory traffic, even on late ACK.
        fsm.act("FAILED", NextState("FAILED"))
