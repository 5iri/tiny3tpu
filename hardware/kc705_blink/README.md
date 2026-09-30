# KC705 open-source LED blink

Target: Xilinx/AMD KC705, `xc7k325tffg900-2`.

All eight user LEDs are driven in a walking pattern, advancing approximately
every 0.34 seconds with the 200 MHz differential clock. LEDs 0–3 use LVCMOS15;
LEDs 4–7 use LVCMOS25.

Successful build database: openXC7/prjxray-db revision
`e8b8e8e46a91334f6232df84d36954323e15a1d1`. Older databases lack required I/O entries.

Build command for the current local tool paths (temporary paths must be retained):

```sh
make BOARD=kc705 \
  NEXTPNR=/Users/siriboi/.apio/packages/openxc7/libexec/nextpnr-xilinx \
  CHIPDB=/tmp/openxc7-blinky-full/xc7k325tffg900-2-apio.bin \
  DB_ROOT=/tmp/kc705-current-db/kintex7 \
  FASM2FRAMES=/Users/siriboi/.apio/packages/openxc7/bin/fasm2frames \
  XC7FRAMES2BIT=/Users/siriboi/.apio/packages/openxc7/bin/xc7frames2bit
```

`make BOARD=kc705 program` builds and loads a volatile JTAG configuration. It
uses only `kc705.xdc`; no constraints from another board are used.
