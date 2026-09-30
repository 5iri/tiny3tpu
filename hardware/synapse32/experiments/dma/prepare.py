"""Materialize isolated DMA integration sources; leave the existing board intact."""
from pathlib import Path
import json
import importlib.util
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
CONTROLLER=ROOT/"multi-core/synapse32_axi_dma.sv"
HEADER=CONTROLLER.read_text().split(");",1)[0]
PORTS=re.findall(r"(input|output)\s+(?:wire|reg)\s*(\[[^\]]+\])?\s*(\w+)",HEADER)
AXI=[port for port in PORTS if port[2].startswith("m_axi_")]


def declarations(ports):
    return ",\n".join(direction+" wire "+width+" "+name for direction,width,name in ports)


def prepare(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    stream=[p for p in PORTS if p[2].startswith(("cmd_","resp_"))]
    fixture="module dma_fixture(\n"+declarations([p for p in PORTS if p not in stream])+");\n"
    fixture+="\n".join("wire "+width+" "+name+";" for direction,width,name in stream)+"\n"
    fixture+="synapse32_axi_dma dma("+",".join("."+name+"("+name+")" for direction,width,name in PORTS)+");\n"
    fixture+="""tiny3tpu_axis transport(.clk(clk),.rst_n(!rst),
        .s_axis_tdata(cmd_data),.s_axis_tkeep(cmd_keep),.s_axis_tlast(cmd_last),
        .s_axis_tvalid(cmd_valid),.s_axis_tready(cmd_ready),
        .m_axis_tdata(resp_data),.m_axis_tkeep(resp_keep),.m_axis_tlast(resp_last),
        .m_axis_tvalid(resp_valid),.m_axis_tready(resp_ready));
    endmodule
"""
    (out/"dma_fixture.sv").write_text(fixture)
    mailbox=(ROOT/"multi-core/synapse32_axis_mailbox.sv").read_text()
    mailbox=mailbox.replace("output reg  [31:0] cpu_rdata,", "output reg  [31:0] cpu_rdata,\n    output wire idle,")
    mailbox=mailbox.replace("wire busy = (state != ST_IDLE);", "wire busy = (state != ST_IDLE);\n    assign idle = !busy && !response_ready;")
    (out/"synapse32_axis_mailbox.sv").write_text(mailbox)
    peripheral=(ROOT/"multi-core/synapse32_tpu_peripheral.sv").read_text()
    extra=""", input wire dma_busy, output wire legacy_idle,
    input wire [31:0] dma_cmd_data, input wire [3:0] dma_cmd_keep,
    input wire dma_cmd_last, input wire dma_cmd_valid, output wire dma_cmd_ready,
    output wire [31:0] dma_resp_data, output wire [3:0] dma_resp_keep,
    output wire dma_resp_last, output wire dma_resp_valid, input wire dma_resp_ready
"""
    peripheral=peripheral.replace("output wire [31:0] cpu_rdata\n", "output wire [31:0] cpu_rdata"+extra)
    start=peripheral.index("    synapse32_axis_mailbox mailbox (")
    end=peripheral.index("    tiny3tpu_axis transport (",start)
    block=peripheral[start:end]
    for old,new in (("req_tdata","mb_data"),("req_tkeep","mb_keep"),("req_tlast","mb_last"),
                    ("req_tvalid","mb_valid"),("req_tready","mb_ready"),("resp_tready","mb_resp_ready")):
        block=block.replace(old,new)
    block=block.replace(".cpu_wr_en(cpu_wr_en)",".cpu_wr_en(cpu_wr_en && !dma_busy)")
    block=block.replace(".cpu_rdata(cpu_rdata),",".cpu_rdata(cpu_rdata), .idle(legacy_idle),")
    block=block.replace(".s_axis_tvalid(resp_tvalid)",".s_axis_tvalid(resp_tvalid && !dma_busy)")
    arbitration="""    wire [31:0] mb_data; wire [3:0] mb_keep;
    wire mb_last, mb_valid, mb_ready, mb_resp_ready;
    assign req_tdata=dma_busy?dma_cmd_data:mb_data;
    assign req_tkeep=dma_busy?dma_cmd_keep:mb_keep;
    assign req_tlast=dma_busy?dma_cmd_last:mb_last;
    assign req_tvalid=dma_busy?dma_cmd_valid:mb_valid;
    assign dma_cmd_ready=dma_busy && req_tready;
    assign mb_ready=!dma_busy && req_tready;
    assign dma_resp_data=resp_tdata; assign dma_resp_keep=resp_tkeep;
    assign dma_resp_last=resp_tlast; assign dma_resp_valid=dma_busy && resp_tvalid;
    assign resp_tready=dma_busy?dma_resp_ready:mb_resp_ready;
"""
    peripheral=peripheral[:start]+arbitration+block+peripheral[end:]
    (out/"synapse32_tpu_peripheral.sv").write_text(peripheral)
    soc=(ROOT/"hardware/synapse32/synapse32_dram_soc.sv").read_text()
    soc=soc.replace("output reg exit_valid, output reg [31:0] exit_code\n", "output reg exit_valid, output reg [31:0] exit_code,\n"+declarations(AXI)+"\n")
    soc=soc.replace("    wire tpu_address =", "    wire dma_address = req_addr[31:5]==(32'h20003000>>5);\n    wire tpu_address =")
    controller="""    wire [31:0] dma_data, dma_cmd_data, dma_resp_data;
    wire [3:0] dma_cmd_keep, dma_resp_keep;
    wire dma_busy, legacy_idle, dma_cmd_last, dma_cmd_valid, dma_cmd_ready;
    wire dma_resp_last, dma_resp_valid, dma_resp_ready;
    synapse32_axi_dma dma(
        .clk(clk),.rst(rst),.legacy_idle(legacy_idle),
        .cpu_wr_en(accept && dma_address && req_write),.cpu_rd_en(accept && dma_address && !req_write),
        .cpu_addr(req_addr[4:0]),.cpu_wdata(req_wdata),.cpu_wstrb(req_wstrb),.cpu_rdata(dma_data),
        .busy(dma_busy),.irq(),
        .cmd_data(dma_cmd_data),.cmd_keep(dma_cmd_keep),.cmd_last(dma_cmd_last),.cmd_valid(dma_cmd_valid),.cmd_ready(dma_cmd_ready),
        .resp_data(dma_resp_data),.resp_keep(dma_resp_keep),.resp_last(dma_resp_last),.resp_valid(dma_resp_valid),.resp_ready(dma_resp_ready),
"""+",".join("."+name+"("+name+")" for direction,width,name in AXI)+");\n"
    soc=soc.replace("    synapse32_tpu_peripheral accelerator (",controller+"    synapse32_tpu_peripheral accelerator (\n"+"""        .dma_busy(dma_busy),.legacy_idle(legacy_idle),
        .dma_cmd_data(dma_cmd_data),.dma_cmd_keep(dma_cmd_keep),.dma_cmd_last(dma_cmd_last),.dma_cmd_valid(dma_cmd_valid),.dma_cmd_ready(dma_cmd_ready),
        .dma_resp_data(dma_resp_data),.dma_resp_keep(dma_resp_keep),.dma_resp_last(dma_resp_last),.dma_resp_valid(dma_resp_valid),.dma_resp_ready(dma_resp_ready),
""")
    soc=soc.replace("else if (tpu_address) local_rdata<=tpu_data;", """else if (tpu_address) begin
                        local_rdata<=tpu_data;
                        if (dma_busy && req_write) local_error<=1;
                    end else if (dma_address) local_rdata<=dma_data;""")
    (out/"synapse32_dram_soc.sv").write_text(soc)
    return out


def rtl(out, dma_read_compare=False, dma_write_last=False):
    sources=[CONTROLLER,ROOT/"multi-core/tiny3tpu_dma_batch.sv"]+sorted((ROOT/"third_party/verilog-axi/rtl").glob("*.v"))
    return [out/"axi_dma_rd.v" if dma_read_compare and p.name=="axi_dma_rd.v" else
            out/"axi_dma_wr.v" if dma_write_last and p.name=="axi_dma_wr.v" else p for p in sources]


def board_sources(out, system_mul=False, dram_command_buffer=False, bus_payload=False, uart_fifo=False,
                  dram_write_capture=False, dram_write_buffer=False, dram_row_hit=False, firmware_opt="-Os", packed_rows=False, wb_decode=False, wb_active=False, dram_refresh_timer=False, dram_local_ready=False, dram_parallel_chooser=False, dram_wide_command=False, tpu_counters=False, registerfile_valid=False, csr_read_direct=False, dram_resetless_write=False, dram_onehot=False, dram_onehot_refresh=False, dram_grant_onehot=False, pe_valid=False, dma_read_compare=False, dma_write_last=False):
    config_text=(ROOT/"hardware/synapse32/kc705_litedram.yml").read_text()
    config=json.loads(config_text[config_text.index('{'):])
    config["user_ports"]["dma"]={"type":"axi","data_width":32,"id_width":1,"block_until_ready":True}
    (out/"kc705_litedram.yml").write_text(json.dumps(config,indent=2)+'\n')
    top=(ROOT/"hardware/synapse32/kc705_synapse32_top.sv").read_text()
    if wb_decode:
        spec=importlib.util.spec_from_file_location("wb_decode",HERE.parent/"wb-decode/prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        top=module.patch_top(top)

    if wb_active:
        assert not wb_decode, "Select only one Wishbone experiment"
        spec=importlib.util.spec_from_file_location("wb_active",HERE.parent/"wb-active/prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        top=module.patch_top(top)

    wires="\n".join("    wire "+width+" "+name+";" for direction,width,name in AXI)+"\n"
    top=top.replace("    kc705_dram memory (",wires+"    kc705_dram memory (")
    connections=[]
    for direction,width,name in AXI:
        suffix=name.removeprefix("m_axi_")
        if suffix in ("awlock","awcache","awprot","arlock","arcache","arprot"): continue
        value=name+'[29:0]' if suffix in ("awaddr","araddr") else "{1'b0,"+name+"}" if suffix in ("awsize","arsize") else name
        connections.append(".user_port_dma_"+suffix+"("+value+")")
    top=top.replace("    kc705_dram memory (", "    kc705_dram memory (\n        "+",\n        ".join(connections)+",\n")
    top=top.replace("    synapse32_dram_soc #(.BOOT_HEX(BOOT_HEX)) soc (", "    synapse32_dram_soc #(.BOOT_HEX(BOOT_HEX)) soc (\n        "+",\n        ".join("."+name+"("+name+")" for direction,width,name in AXI)+",\n")
    (out/"kc705_synapse32_top.sv").write_text(top)
    script=(ROOT/"tools/kc705_open_build.py").read_text()
    script=script.replace('ROOT = Path(__file__).resolve().parents[1]', 'ROOT = Path('+repr(str(ROOT))+')')
    script=script.replace('ROOT / "hardware/synapse32/kc705_litedram.yml"', 'Path('+repr(str(out/"kc705_litedram.yml"))+')')
    if registerfile_valid:
        marker='    sources = [cpu / "rtl/core_modules/uart.v"]'
        assert script.count(marker)==1
        script=script.replace(marker,'    cpu_sources = [Path('+repr(str(out/"registerfile.v"))+') if s.name == "registerfile.v" else s for s in cpu_sources]\n'+marker)
    if csr_read_direct:
        marker='    sources = [cpu / "rtl/core_modules/uart.v"]'
        assert script.count(marker)==1
        script=script.replace(marker,'    cpu_sources = [Path('+repr(str(out/"csr_file.v"))+') if s.name == "csr_file.v" else s for s in cpu_sources]\n'+marker)
    if dram_command_buffer or dram_write_capture or dram_write_buffer or dram_row_hit or dram_refresh_timer or dram_local_ready or dram_parallel_chooser or dram_grant_onehot or dram_wide_command or dram_resetless_write or dram_onehot or dram_onehot_refresh:
        selected=sum(map(bool,(dram_refresh_timer,dram_row_hit,dram_local_ready,dram_parallel_chooser,dram_grant_onehot,dram_wide_command,dram_resetless_write,dram_onehot,dram_onehot_refresh)))
        parallel_timer=dram_refresh_timer and dram_parallel_chooser
        grant_timer=dram_refresh_timer and dram_grant_onehot
        assert selected<=1 or (selected==2 and (parallel_timer or grant_timer)), "Only proven DDR combinations may be composed"
        generator=HERE.parent/("dram-grant-timer" if grant_timer else "dram-parallel-timer" if parallel_timer else "dram-onehot-refresh" if dram_onehot_refresh else "dram-onehot" if dram_onehot else "dram-resetless-write" if dram_resetless_write else "dram-wide-command" if dram_wide_command else "dram-grant-onehot" if dram_grant_onehot else "dram-parallel-chooser" if dram_parallel_chooser else "dram-local-ready" if dram_local_ready else "dram-refresh-timer" if dram_refresh_timer else "dram-row-hit" if dram_row_hit else "dram-write-buffer" if dram_write_buffer else
                               "dram-write-capture" if dram_write_capture else "dram-command-buffer")/"generate.py"
        assert 'sys.executable, "-m", "litedram.gen"' in script
        script=script.replace('sys.executable, "-m", "litedram.gen"',
                              'sys.executable, Path('+repr(str(generator))+')')
    script=script.replace('-march=rv32i_zicsr_zifencei','-march=rv32im_zicsr_zifencei')
    assert firmware_opt in ("-Os","-O2","-O3")
    script=script.replace('"-Os"','"'+firmware_opt+'"')
    if packed_rows:
        script=script.replace('"'+firmware_opt+'"','"'+firmware_opt+'", "-DTINY3TPU_DMA_PACKED_ROWS"')
    script=script.replace('firmware / "stream_smoke.c"', 'Path('+repr(str(out/"stream_smoke.c"))+')')
    script=script.replace('ROOT / "src/axis_mailbox.c", ROOT / "src/mmio_backend.c",',
                          'ROOT / "src/axis_mailbox.c", ROOT / "src/mmio_backend.c", ROOT / "src/dma_backend.c",')
    replacements={name:str(out/name) for name in ("synapse32_dram_soc.sv","synapse32_axis_mailbox.sv",
                                               "synapse32_tpu_peripheral.sv","kc705_synapse32_top.sv")}
    if pe_valid:replacements["pe.v"]=str(out/"pe.v")
    if tpu_counters:replacements["tpu_core_wrapper.sv"]=str(out/"tpu_core_wrapper.sv")
    if bus_payload:replacements["synapse32_memory_sequencer.sv"]=str(out/"synapse32_memory_sequencer.sv")
    if uart_fifo:replacements["uart.v"]=str(out/"uart.v")
    if system_mul:
        # Slang elaborates the CPU separately and consumes its parameters. Set
        # the top-level override there; do not reapply it in the RTLIL wrapper.
        script=script.replace("--top riscv_cpu -I{}", "--top riscv_cpu -G SYSTEM_MUL=1 -I{}")
        soc=(out/"synapse32_dram_soc.sv").read_text()
        assert "riscv_cpu #(.SYSTEM_MUL(1)) cpu (" in soc
        target=out/"synapse32_dram_soc_synth.sv"
        target.write_text(soc.replace("riscv_cpu #(.SYSTEM_MUL(1)) cpu (", "riscv_cpu cpu ("))
        replacements["synapse32_dram_soc.sv"]=str(target)
    injected="    replacements = "+repr(replacements)+"\n    sources = [Path(replacements.get(p.name, str(p))) for p in sources]\n"
    injected+="    sources += [Path(p) for p in "+repr(list(map(str,rtl(out,dma_read_compare=dma_read_compare,dma_write_last=dma_write_last))))+"]\n"
    script=script.replace("    def quote(path):",injected+"    def quote(path):")
    (out/"board_build.py").write_text(script)


if __name__=="__main__":
    import sys
    prepare(Path(sys.argv[1]))
