# KC705 ADV7511 initialization

`src/kc705_hdmi_init.sv` implements fixed 640×480 or 1280×720, 60 Hz, video-only HDMI modes. Set `VIDEO_720P=1` and `CLOCK_HZ=74250000` for 720p; the default is VGA at 25.2 MHz. `reset` is active high; `scl` and `sda` are open drain. `mux_reset_n` drives the board's mux reset. The module owns the I²C bus; it does not arbitrate with another master.

The KC705 board bus uses `HDMI_D[7:0]` for Y and `HDMI_D[15:8]` for alternating Cb/Cr. The board's net labels must not be treated as the ADV7511's D-pin numbering. The PCA9548 mux is at seven-bit address `0x74`; HDMI is channel 5, selected with `0x20`. P23 must release the mux reset. Board pin assignments and the mux come from AMD [UG810 v1.9, Tables 1-21 and Figure 1-22](https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content).

The mode follows ADI's [KC705 no-OS transmitter initialization](https://github.com/analogdevicesinc/no-OS/blob/main/projects/adv7511/src/transmitter.c): eight bits per component, SDR 4:2:2, separate sync, input style 2, right justification, BT.601 input and RGB output. Board data is `{Cb, Y}` on the first active pixel and `{Cr, Y}` on the next; DE must start a chroma pair. This byte order is explicit in ADI's [ad_ss_444to422](https://github.com/analogdevicesinc/hdl/blob/hdl_2017_r1/library/common/ad_ss_444to422.v) and is carried unchanged through [axi_hdmi_tx_core](https://github.com/analogdevicesinc/hdl/blob/hdl_2017_r1/library/axi_hdmi_tx/axi_hdmi_tx_core.v), [KC705 system_top](https://github.com/analogdevicesinc/hdl/blob/hdl_2017_r1/projects/adv7511/kc705/system_top.v), and its [pin constraints](https://github.com/analogdevicesinc/hdl/blob/hdl_2017_r1/projects/adv7511/kc705/system_constr.xdc).

The first physical load on 2026-10-11 produced a visible image with green/purple color bars. The original FPGA packed `{Y,C}` and the simulation decoder assumed that same incorrect board order. The corrected regression includes fixed board-bus vectors, including white `0x80EB` and black `0x8010`, independently of the generic RGB/YCC conversion oracle.

After the corrected image was loaded into FPGA SRAM on the same day, the user confirmed: "Bars correct and banana yellow." The bitstream hash, programmer result, and visual confirmation are recorded in `build-kc705-hdmi/hardware-validation/color-fix-load-report.json`.

Register meanings and coefficients are from ADI's [ADV7511 Programming Guide, revision G](https://www.analog.com/media/en/technical-documentation/user-guides/ADV7511_Programming_Guide.pdf), especially Tables 14, 18, 28, 30, 59, 67 and 97. The actual ordered writes are the `setting()` ROM, using seven-bit device address `0x39`.

| Writes | Purpose |
| --- | --- |
| `41=10` | Power up, preserving reserved bit 4 |
| `98,9A,9C,9D,A2,A3,E0,F9` | Required fixed settings, Table 14 |
| `15=01,16=34,48=08,17=00` | Input mapping; external DE; sync polarity passthrough |
| `18..2F` | Table 59 limited BT.601 → full RGB coefficients; atomic CSC update |
| `3B=C0,3C=01` | Manual ×1 repetition and VIC 1; preserve reserved `3B[7]` |
| `AF=06` | HDMI, with HDCP/encryption disabled |
| `44=11,0B=0E,0C=00` | AVI enabled; audio, N/CTS and audio InfoFrame disabled |
| `55=02,56=10,57=08` | RGB, underscan, 4:3, full range; automatic AVI checksum |
| `BA=60,A1=00,4B=80,40=80` | Zero capture-clock delay; TMDS on; clear AVMUTE via GCP |

In 720p mode, `17=02` sets the input aspect to 16:9, `3C=04` selects VIC 4,
and `56=20` advertises 16:9 RGB in the AVI InfoFrame (Programming Guide Tables
29 and 67). Sync polarity passes through: the FPGA supplies positive H/V sync
for 720p. The FPGA-to-transmitter bus still uses BT.601 limited-range YCbCr;
the explicitly programmed CSC converts it to full-range RGB before HDMI.
Consequently the output is RGB with no YCbCr colorimetry flag, even at 720p.
Changing resolution does not silently switch only one half of the color conversion.

The 720p raster is 1280×720 active / 1650×750 total, 74.25 MHz, matching ADI's
[video timing reference](https://ez.analog.com/video/f/q-a/574610/adv7842-hdmi-vde-adjustment).
Its pixel clock uses the fractional feedback supported by AMD's
[MMCME2_ADV](https://docs.amd.com/r/2025.1-English/ug953-vivado-7series-libraries/MMCME2_ADV).
The nominal forwarded-clock half-cycle shrinks to 6.734 ns; the earlier physical
VGA color confirmation does not validate this new mode's output timing.

The controller waits 200 ms after reset, selects the mux, then waits for HPD. It clears the old sticky HPD event before programming and checks HPD plus that event again afterward. `configured` becomes high only after all writes acknowledge and the transmitter reports PLL lock. Every 100 ms it polls HPD, its sticky event and PLL lock. An unplug clears `configured`; reattachment reloads the entire table. A short HPD pulse is also caught by the sticky event. The FPGA should keep the pixel clock and sync signals running while blanking DE until configuration completes.

Transactions retry at most three total attempts. SDA stuck low triggers nine recovery clocks and a STOP before a fresh START. SCL stretching is allowed for at most 10 ms per uninterrupted stretch. Exhausted attempts or 20 unsuccessful PLL checks latch `error`, clear `configured` and release the bus until reset. Missing HPD is a waiting state, not an error. The quarter-period divider rounds upward, so SCL does not exceed the requested 100 kHz, including at clocks not divisible by 400 kHz.

This is a fixed-mode bring-up controller: no EDID negotiation, audio, HDCP, CEC service or multi-master support. `configured` reports register/HPD/PLL state; it does not itself prove that a monitor displayed the image. The user has separately confirmed the corrected colors on the connected monitor. Physical I²C rise time, external timing bounds, and compatibility with other monitors remain unqualified.

Run the pin-level test with:

```sh
python3 hardware/kc705_hdmi/tb/test_init.py --out build-kc705-hdmi/init
python3 hardware/kc705_hdmi/tb/test_init.py --video-mode 720p --out build-mjx/720p-init
```

The behavioral mux/transmitter uses resolved open-drain signals with pull-ups, parses addresses and register writes, supplies read bits, and verifies repeated START and the master's final NACK. Cases cover startup without a monitor, exact format/CSC/AVI/fixed settings, an existing TMDS mute state, unplug/replug, a short HPD pulse, HPD loss during initialization, NACK positions and retry limits, reset during transfer, clock stretching, recoverable/permanent SDA faults, permanent SCL faults and absent PLL lock. SCL high/low durations and maximum frequency are checked. Poll/startup/error delays are shortened for simulation; the production clock frequency is retained. The model does not simulate the ADV7511's video pipeline.
