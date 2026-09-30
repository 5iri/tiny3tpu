# Cached one-hot DDR command grant

This opt-in candidate builds on parallel masked command selection. The existing
binary round-robin grant remains unchanged. An eight-bit one-hot copy is updated
in the same branch and on the same enabled edge as the binary grant. Command
selection uses those registered bits directly. Reset selects bank zero for both
representations. There is no additional arbitration or command cycle.

The generator changes only its in-process LiteDRAM module; installed packages
and the sibling Synapse32 repository remain untouched. The corrected write-data
buffer adapter is retained.

Validation in `build-ddr-grant-onehot/results.json`:

- Inductive equivalence for the complete eight-bank chooser under arbitrary
  request, type-filter, ready and reset inputs, including binary grant equality
  and `grant_onehot == 1 << grant` as an invariant.
- All fourteen upstream multiplexer tests pass.
- Generated source and dependency hashes gate synthesis.

`build-ddr-dma-grant-onehot/system/results.json` exactly matches the accepted
selector smoke PROFILE, METRICS and DMA records: 106,588 instructions, 142,895
enabled CPU cycles, 789,205 system cycles, and 1,130 beats / 87 bursts per
transfer direction. This behavioral SoC model is not a physical DDR calibration
test; board-controller cycle equivalence is covered by the separate proof.

Synthesis adds sixteen flip-flops (fourteen FDRE, two FDSE). Full placement
seed 8 gives 90.95 MHz system / 104.33 MHz CPU; seed 4 gives 91.27/107.91 MHz.
These do not beat the best local selector placement at 97.53/101.68 MHz. The
candidate stays opt-in and is not promoted. A separately verified combination
with the registered refresh/ZQCS terminal flag is being tested.
