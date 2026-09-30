BOARD ?= kc705

ifeq ($(BOARD),kc705)
PART := xc7k325tffg900-2
XDC := kc705.xdc
else
$(error Unsupported BOARD '$(BOARD)'; this project targets only kc705)
endif

BUILD := build

# Point these at an installed openXC7 Kintex-7 toolchain. They can be
# overridden on the make command line.
NEXTPNR ?= nextpnr-xilinx
CHIPDB ?= $(PART).bin
DB_ROOT ?= /opt/openxc7/prjxray-db/kintex7
FASM2FRAMES ?= fasm2frames
XC7FRAMES2BIT ?= xc7frames2bit

.PHONY: all clean program
.DELETE_ON_ERROR:

all: $(BUILD)/kc705_blink.bit

$(BUILD):
	mkdir -p $@

$(BUILD)/kc705_blink.json: blink.v | $(BUILD)
	yosys -p 'synth_xilinx -flatten -abc9 -arch xc7 -top blink; write_json $@' $<

$(BUILD)/kc705_blink.fasm: $(BUILD)/kc705_blink.json $(XDC)
	$(NEXTPNR) --freq 200 --chipdb $(CHIPDB) --xdc $(XDC) --json $< --write $(BUILD)/kc705_blink_routed.json --fasm $@

$(BUILD)/kc705_blink.frames: $(BUILD)/kc705_blink.fasm
	$(FASM2FRAMES) --part $(PART) --db-root $(DB_ROOT) $< > $@

$(BUILD)/kc705_blink.bit: $(BUILD)/kc705_blink.frames
	$(XC7FRAMES2BIT) --part_file $(DB_ROOT)/$(PART)/part.yaml --part_name $(PART) --frm_file $< --output_file $@

program: $(BUILD)/kc705_blink.bit
	openFPGALoader -b kc705 --bitstream $<

clean:
	rm -rf $(BUILD)
