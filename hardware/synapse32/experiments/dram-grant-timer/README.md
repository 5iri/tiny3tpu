# Cached grant and registered refresh terminal flag

This composes the separately proven cached one-hot command grant with the
registered refresh/ZQCS timer terminal flag. The latter predicts `count == 0`
from the previous count on the same update edge, preserving the original `done`
waveform, including reset and period-one behavior. It adds no command cycle.

`build-ddr-grant-timer/results.json` verifies current component proof hashes,
byte-identical generated component source, and all seventeen combined upstream
multiplexer/refresher tests. The corrected write-data buffer adapter is retained.

`build-ddr-dma-grant-timer/system/results.json` matches the selector smoke
profile: 106,588 instructions / 142,895 enabled CPU edges; 789,205 system cycles;
1,130 beats and 87 bursts per direction. The board-only components are covered
by their formal cycle-equivalence proofs; this smoke model does not establish
physical DDR behavior. Synthesis completed. Seeds 8/4/2/6 report partial system
Fmax of 84.22/87.42/90.75/72.78 MHz; none improves the retained placement.
These historical figures omit registered DSP and memory timing paths, as
explained in [current status](../CURRENT_STATUS.md). No promotion is made.
