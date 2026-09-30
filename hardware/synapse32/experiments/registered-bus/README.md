# Registered request payload experiment

The sequencer drives the bus request payload directly from registers, removing
the request-state address mux. It fills those registers on existing state
transitions, adding no request or CPU cycles. Valid requests, backpressure,
response handling, faults and the CPU clock-enable sequence remain equivalent.

`prove.py` proves the candidate against the full original sequencer by temporal
induction, with arbitrary bus and CPU inputs. It compares request payloads when
valid and all control/CPU outputs every cycle. A matching internal state vector
supports induction; no traffic assumptions restrict the proof. Unit tests and
the real-CPU DDR memory-model/TPU workload pass with the unchanged cycle count.

| Seed-4 full board route | CPU MHz | System MHz |
| --- | ---: | ---: |
| Forwarding retime baseline (`build-ddr-retime`) | 45.62 | 62.48 |
| Registered bus (`build-ddr-retime-regbus`) | 45.28 | 74.30 |
| Registered bus + ABC9 (`build-ddr-retime-regbus-abc9`) | 39.28 | 50.39 |
| Stalling MUL baseline (`build-ddr-mul`) | 61.21 | 77.04 |
| Stalling MUL + registered bus (`build-ddr-regbus`) | 60.79 | 70.13 |

The registered bus improves the system result with the original-latency CPU but
does not close either 100 MHz target. ABC9 regresses both results. The stalling
MUL combinations are excluded because the CPU IPC benchmark fails. These are
single-seed diagnostics, not promoted configurations. The unsupported DCI
constraint diagnostic remains in the physical flow.

```sh
python3 hardware/synapse32/experiments/registered-bus/prove.py --out build-ddr-regbus-proof-new
python3 hardware/synapse32/experiments/registered-bus/run.py verify \
  --cpu-build build-ddr-retime --out build-ddr-retime-regbus-new
python3 hardware/synapse32/experiments/registered-bus/run.py synth \
  --cpu-build build-ddr-retime --out build-ddr-retime-regbus-new
python3 hardware/synapse32/experiments/registered-bus/run.py route \
  --cpu-build build-ddr-retime --out build-ddr-retime-regbus-new
```

Completed routes return failure when the acceptance report rejects timing,
regardless of nextpnr's exit code. No bitstream is generated or programmed.
