# AXI4-Lite accelerator registers

`multi-core/tiny3tpu_axi.sv` exposes a 32-bit AXI4-Lite slave with 8-bit byte
addresses. It instantiates `top` explicitly as two 4x4 cores with `DW=8` and
`CW=32`.

## Interface

The module is `tiny3tpu_axi` and uses the exact ports below:

```text
s_axi_aclk, s_axi_aresetn
s_axi_awaddr[7:0], s_axi_awprot[2:0], s_axi_awvalid, s_axi_awready
s_axi_wdata[31:0], s_axi_wstrb[3:0], s_axi_wvalid, s_axi_wready
s_axi_bresp[1:0], s_axi_bvalid, s_axi_bready
s_axi_araddr[7:0], s_axi_arprot[2:0], s_axi_arvalid, s_axi_arready
s_axi_rdata[31:0], s_axi_rresp[1:0], s_axi_rvalid, s_axi_rready
```

`s_axi_aresetn` is active-low and resets the AXI wrapper and accelerator.
`AWPROT` and `ARPROT` are accepted but unused.

## Register map

| Offset | Name | Access | Description |
| ---: | --- | --- | --- |
| `0x00` | CTRL | RW | Control pulse bits and persistent strict-readback shadow |
| `0x04` | UBUF_CFG | RW | UBUF bank/core/row/column selection |
| `0x08` | UBUF_DATA | RW | Operand data; accelerator consumes low signed 8 bits |
| `0x0c` | CRD_CFG | RW | C-result core/row/column selection |
| `0x10` | STATUS | RO | Bit 0 is busy/launch-pending; bit 1 is sticky DONE |
| `0x14` | CRD_DATA_LO | RO | Latched signed 64-bit result, bits `[31:0]` |
| `0x18` | CRD_DATA_HI | RO | Latched signed 64-bit result, bits `[63:32]` |
| `0x40..0x7c`, aligned | PACKED_ROW | WO | Four operand bytes; address selects core, bank and row |

All other offsets, including writes to the read-only registers, return AXI
`SLVERR` (`2'b10`) and have no side effects. Valid reads and writes return
`OKAY` (`2'b00`).

## Fields and behavior

`PACKED_ROW` address is `0x40 + core*32 + select_b*16 + row*4`.
Byte lane 0 supplies column 0, through lane 3 supplying column 3. Each
selected `WSTRB` lane writes one signed 8-bit operand; unselected lanes retain
their existing operand. The wrapper serializes the stores over four clocks
and returns B only after the final store has been consumed. It accepts no
further write during serialization or a stalled B response. AW and W can still
arrive independently. Reads and unaligned accesses return `SLVERR`.

A packed write while the accelerator is busy or launch-pending returns
`SLVERR` without operand updates. Reset cancels an in-progress packed write and
clears accelerator storage. Packed writes use the UBUF shadow registers as
their staging registers: afterward UBUF_CFG selects the addressed row's column
3 and UBUF_DATA contains zero-extended byte 3, including with zero strobes.
Software must set both shadows again before a subsequent legacy cell write.
This aperture uses ordinary register writes through the existing AXI DMA
command format; it adds no CPU instructions or asynchronous tile queue.

The generic C QGEMM driver uses this aperture, retains unchanged packed rows
within a call, and chooses row-parallel or reduction-parallel core tiling from
matrix dimensions. It requires exclusive device ownership until the callback
returns and retains no cached hardware state between calls. Sign-extension and
final int32 overflow checks still apply to result reads/partial accumulation.

`UBUF_CFG` fields are:

```text
bit 0       select B bank (0 = A, 1 = B)
bit 8       core (0 or 1)
bits 17:16  row (0..3)
bits 25:24  column (0..3)
```

`CRD_CFG` uses the same core, row, and column fields; bit 0 is ignored.
Register shadows retain all written bits and support firmware write/read
verification. `WSTRB` merges only the selected bytes into the persistent
shadow registers. The accelerator uses only the fields listed above.

`STATUS` is defined as follows:

```text
bit 0  BUSY: top.busy OR a one-cycle START launch pending in the wrapper
bit 1  DONE: sticky completion indication from top.done (also visible during
             the current top.done pulse before the latch updates)
```

DONE is set when the existing `top.done` pulse is observed. It is cleared by
reset or by an accepted CTRL START write sampled while `top.busy` is low.
Therefore software may poll DONE without having to observe the transient
busy interval. A START write accepted while `top.busy` is high is rejected by
the existing `top`, and does not clear DONE or create a completion indication.
The launch-pending contribution to BUSY closes the cycle between accepting an
idle START and `top` asserting its registered busy output.

`CTRL` bits are pulses on the accepted write, not level-sensitive enables:

```text
bit 0  START: start the accelerator
bit 1  UBUF_WR: write the selected UBUF cell
bit 2  CRD_RD: select and latch the selected C cell
```

Each set pulse bit is emitted for exactly one accelerator clock after the
complete AXI write (both AW and W) has been accepted. The CTRL shadow stores
the written value, so a firmware read immediately after a write sees the
value even though the accelerator controls are pulses. Partial writes obey
`WSTRB`; a pulse is emitted only when byte 0 is strobed and the corresponding
bit is set in the accepted write data.

For `CRD_RD`, `top_c_rd_data` is captured on the clock after the one-cycle
`c_rd_en` pulse. The signed 32-bit value is sign-extended to 64 bits before
being exposed through `CRD_DATA_LO` and `CRD_DATA_HI`. Firmware should allow a
read transaction to elapse after the CRD pulse before reading the result, as
the supplied `firmware.c` does with a STATUS read.

AW and W are latched independently and may arrive in either order. A write
response is held until `BREADY`; a read response is held until `RREADY`, so
backpressure does not drop transactions. Only one write response and one read
response are outstanding at a time.

The existing `top` determines accelerator-side busy behavior. START is
accepted at the AXI interface but is ignored by `top` while it is busy (and
during its one-cycle post-completion `ST_DONE` state). UBUF_WR is accepted at
the AXI interface but `top` writes the UBUF only when its pre-write `busy` is
low. Consequently, a CTRL write containing START and UBUF_WR while idle can
start the operation and write the operand on the same clock; issuing either
while busy does not abort or alter the running operation. CRD_RD remains a
one-cycle read pulse and updates the result latch independently of busy.
