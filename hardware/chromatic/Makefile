# Point CAD at an OSS CAD Suite with GW5A-25A / Himbaechel support.
CAD ?= $(abspath ../../../fun/pikachu/.tools/oss-cad-suite)
CORE := ../../multi-core/tpu_core_wrapper.sv ../../systolic_array/rtl/NxN_systolic_array.v ../../systolic_array/rtl/pe.v
SOURCES := src/buttons.sv src/banana_renderer.sv src/framebuffer.sv src/scene.sv src/video.sv src/panel_init.sv src/scanout.sv src/top.sv $(CORE)
.PHONY: all assets lint test load
all: build/banana.fs
assets:
	python3 tools/assets.py
build/synth.json: $(SOURCES) Makefile src/font.vh src/panel-init.bin assets/vertices.hex assets/rotations.hex assets/faces.hex
	mkdir -p build
	$(CAD)/bin/yosys -ql build/synthesis.log -p 'read_verilog -D SYNTHESIS -I src -sv $(SOURCES); synth_gowin -top top -family gw5a -nolutram; techmap -map +/techmap.v t:$$buf; clean; check; write_json $@'
build/routed.json: build/synth.json constraints/chromatic.cst
	$(CAD)/bin/nextpnr-himbaechel --device GW5A-EV25UG256CC1/I0 --vopt family=GW5A-25A --vopt cst=constraints/chromatic.cst --freq 33.555 --json $< --write $@ --report build/timing.json --log build/place-route.log
build/banana.fs: build/routed.json
	$(CAD)/bin/gowin_pack -d GW5A-25A -o $@ $<
lint:
	verilator --lint-only --top-module top -Wno-TIMESCALEMOD verilator.vlt -Isrc $(SOURCES)
test:
	python3 tools/test.py
load: build/banana.fs
	openFPGALoader --cable gwu2x --freq 1000000 --write-sram $<
