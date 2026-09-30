# Capture bus payload independently of request validation

This derives from `registered-bus` and captures the candidate payload on every
ST_SETTLE edge. Alignment, conflict and validity checks still decide whether
the sequencer issues a request or reports a fault. This removes validation
logic from the payload register's enable path without adding a cycle. Payload
values captured for rejected requests are not observed by the bus.

The original sequencer and candidate pass temporal induction for all CPU and
bus inputs: state, CPU responses and control outputs match on every cycle;
payload matches whenever a request is valid, including under backpressure.

```sh
python3 hardware/synapse32/experiments/bus-payload/prepare.py --out build-ddr-bus-payload
python3 hardware/synapse32/experiments/registered-bus/prove.py \
  --out build-ddr-bus-payload/proof \
  --candidate build-ddr-bus-payload/synapse32_memory_sequencer.sv
```

Enable with `dma/run.py --bus-payload`. It is included in the combined
`system-alu` simulation and route; there is no standalone routed Fmax claim.
