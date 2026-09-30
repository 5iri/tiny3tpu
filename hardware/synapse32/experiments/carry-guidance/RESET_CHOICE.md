# Reset cofactor experiment

`build-grade2-reset-choice/patch.json` composes with the linear counter patch.
The TPU transport bridge response-code CE cone (FF59914) is cofactored on reset.
Seven added combinational LUTs compute the two reset cases and a final mux.
All 8,192 cut cases and actual Xilinx primitive SAT pass. Corrupt early/final
INITs and injection of reset into an early cone are rejected. No state or
execution cycle changes.

The full fixed-layout route `build-grade2-reset-choice-route` passes logical
and placement integrity. Its target FF59914 CE improves from 10.855 to
**7.690 ns**, but global probes regress to **10.936 / 10.936 / 11.036 ns**.
Native reports are 90.61 / 97.32 MHz, with 154 failing endpoint/domain pairs.
DMA status FIFO length becomes the worst endpoint. This result is not selected.
The exact lossless replay and compatible-route reuse both pass. The reuse
route `build-grade2-reset-choice-cross-reuse` reaches **10.781 ns in all three
probes**, tying the retained worst diagnostic. Native reports are 92.76 MHz
system / 100.53 MHz CPU; expanded CPU-to-system still exceeds 10 ns. The bridge
CE target is **7.724 ns**. All **19,098 imported route resource sets** are
unchanged, and independent integrity passes. The full timing gate still rejects
this result; native CPU timing passing does not establish whole-SoC closure.

The full timing gate rejects this result. Generic and carry delays, clock
skew/hold, reset recovery/removal and DDR IO remain unqualified. The packed
combinational proofs compose with parent workload evidence; this is not a fresh
workload simulation or whole-RTL synthesis.
