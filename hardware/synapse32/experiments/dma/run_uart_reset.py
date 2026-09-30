#!/usr/bin/env python3
"""Validate open DMA and materialize the isolated CPU/DDR/TPU integration."""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys
from prepare import prepare,rtl,board_sources,ROOT,HERE


def run(command,log):
    print("Running",log.name,flush=True)
    with log.open("w") as output:
        rc=subprocess.run(list(map(str,command)),stdout=output,stderr=subprocess.STDOUT).returncode
    if rc:
        print(log.read_text()[-6000:]);raise SystemExit(rc)


def accelerator_rtl():
    return [ROOT/"multi-core"/name for name in ("tiny3tpu_axis.sv", "tiny3tpu_axis_bridge.sv", "tiny3tpu_axi.sv", "top.v", "tpu_core_wrapper.sv")] + [ROOT/"systolic_array/rtl"/name for name in ("NxN_systolic_array.v", "pe.v")]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("prepare","unit","system","stress","synth","route"))
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--cpu-overlay-dir",type=Path,default=ROOT/"build-ddr-shared-mul/overlay")
    parser.add_argument("--shapes-file",type=Path,help="Custom M,K,N tuples for stress; fixed-buffer bounds are checked")
    parser.add_argument("--packed-rows",action="store_true",help="Opt-in packed operand rows; faster GEMM but currently below the default IPC floor")
    parser.add_argument("--seed",type=int,default=4)
    parser.add_argument("--firmware-opt",choices=("-Os","-O2","-O3"),default="-Os",help="Compiler optimization shared by simulation and board firmware")
    parser.add_argument("--system-mul",action="store_true",
                        help="Enable the system-mul CPU overlay (requires four system clocks per CPU step)")
    parser.add_argument("--dram-command-buffer",action="store_true",
                        help="Use an isolated registered LiteDRAM width-converter command buffer in board generation")
    parser.add_argument("--wb-decode",action="store_true",help="Predecode Wishbone address regions at the existing capture edge (board only)")
    parser.add_argument("--wb-active",action="store_true",help="Capture per-target Wishbone active enables (board only)")
    parser.add_argument("--csr-valid-decode",action="store_true",help="Factor CSR validity range checks (implies direct read)")
    parser.add_argument("--csr-read-direct",action="store_true",help="Remove redundant CSR read-validity decode")
    parser.add_argument("--registerfile-valid",action="store_true",help="Use validity bits for register-file reset semantics")
    parser.add_argument("--tpu-spm-valid",action="store_true",help="Use validity bits for TPU input scratchpad reset; implies narrow counters")
    parser.add_argument("--tpu-feed-decode",action="store_true",help="Decode fixed TPU feed slots; implies narrow counters")
    parser.add_argument("--pe-valid",action="store_true",help="Mask reset-free PE accumulator payload to allow DSP output registers")
    parser.add_argument("--tpu-counters",action="store_true",help="Narrow TPU feed/flush phase counters without cycle changes")
    parser.add_argument("--dma-read-limit",action="store_true",help="Factor DMA read burst capacity; implies read comparison")
    parser.add_argument("--dma-read-compare",action="store_true",help="Use equivalent direct DMA read burst-completion comparison")
    parser.add_argument("--dma-write-limit",action="store_true",help="Factor DMA burst capacity into a seven-bit page/burst limit")
    parser.add_argument("--dma-write-narrow",action="store_true",help="Narrow bounded DMA burst byte count; preserve cycle counters")
    parser.add_argument("--dma-write-last",action="store_true",help="Use equivalent direct DMA write last-cycle comparisons")
    parser.add_argument("--dma-write-short",action="store_true",help="Derive DMA first last-cycle flag directly from length/page boundary; implies write-last")
    parser.add_argument("--boot-local-enable",action="store_true",help="Remove irrelevant external-ready decode from boot RAM enable")
    parser.add_argument("--boot-address-decode",action="store_true",help="Use exact prefix decode for 64 KiB boot RAM")
    parser.add_argument("--uart-local-accept-proof",type=Path,default=ROOT/"build-ddr-uart-local-accept",help="Proof directory for the exact current UART acceptance source")
    parser.add_argument("--uart-local-accept",action="store_true",help="Remove external-ready dependency from UART acceptance")
    parser.add_argument("--uart-zero-flags",action="store_true",help="Track UART baud zero flags at their existing update edges; implies UART address decode")
    parser.add_argument("--uart-address-decode",action="store_true",help="Use equivalent UART bitwise address decode; includes UART control overlay")
    parser.add_argument("--dram-resetless-write",action="store_true",help="Remove reset from unowned wide write payload (board only)")
    parser.add_argument("--dram-wide-command",action="store_true",help="Queue completed wide native commands (board only)")
    parser.add_argument("--dram-onehot-refresh",action="store_true",help="Explicit one-hot DDR refresher FSM (board only)")
    parser.add_argument("--dram-onehot",action="store_true",help="Explicit one-hot DDR bank FSMs (board only)")
    parser.add_argument("--dram-grant-onehot",action="store_true",help="Cache one-hot DDR command grant on its original arbitration edge (board only)")
    parser.add_argument("--dram-parallel-chooser",action="store_true",help="Parallel masked DDR command selection (board only)")
    parser.add_argument("--dram-local-ready",action="store_true",help="Use bank-local filtered command validity (board only)")
    parser.add_argument("--dram-refresh-timer",action="store_true",help="Register exact refresh timer zero flag (board only)")
    parser.add_argument("--bus-payload",action="store_true")
    parser.add_argument("--uart-fifo",action="store_true")
    parser.add_argument("--uart-rx-fifo",action="store_true",help="Apply proved RX and TX FIFO payload reset separation")
    parser.add_argument("--uart-control",action="store_true",help="Use proved combinational UART FIFO events; includes RX/TX payload separation")
    parser.add_argument("--dram-write-capture",action="store_true",
                        help="Capture unfilled DDR write lanes independently of input valid; includes command buffering")
    parser.add_argument("--dram-write-buffer",action="store_true",
                        help="Use a two-entry native wide write FIFO; includes command buffering and write capture")
    parser.add_argument("--dram-row-hit",action="store_true",help="Use proved bank row-hit lookahead; includes the corrected two-entry write buffer")
    parser.add_argument('--uart-reset-control',action='store_true',help='Remove redundant reset from UART state-control inputs using full integration proof')
    args=parser.parse_args();out=prepare(args.out)
    if args.uart_reset_control and not (args.uart_local_accept and args.uart_address_decode):parser.error('UART reset control requires local acceptance and address decode')
    shapes=[[1,1,1],[4,8,4],[7,13,9],[8,16,8],[3,5,6]] if args.mode=="stress" else [[5,11,7]]
    if args.shapes_file:
        if args.mode!="stress": parser.error("--shapes-file requires stress mode")
        shapes=json.loads(args.shapes_file.read_text())
        if not isinstance(shapes,list) or not 1<=len(shapes)<=256:
            parser.error("Expected 1..256 shapes")
        for shape in shapes:
            if not isinstance(shape,list) or len(shape)!=3 or any(type(x)!=int or x<=0 for x in shape):
                parser.error("Each shape must be three positive integers M,K,N")
            m,k,n=shape
            if m*k>4096 or k*n>4096 or m*n>1024:
                parser.error("Shape exceeds disjoint test buffers: M*K and K*N <=4096, M*N <=1024")
    shape_literal="{"+",".join("{"+",".join(map(str,x))+"}" for x in shapes)+"}"
    result_count=sum(m*n for m,k,n in shapes)

    if args.tpu_feed_decode and args.tpu_spm_valid:parser.error("Separate TPU feed/SPM experiments")
    if args.tpu_feed_decode or args.tpu_spm_valid:args.tpu_counters=True
    tpu_experiment="tpu-spm-valid" if args.tpu_spm_valid else "tpu-feed-decode" if args.tpu_feed_decode else "tpu-counters"
    tpu_evidence="build-tpu-spm-valid" if args.tpu_spm_valid else "build-tpu-feed-decode" if args.tpu_feed_decode else "build-tpu-counters-n4-compositional"
    if args.csr_valid_decode:args.csr_read_direct=True
    if args.dma_read_limit:args.dma_read_compare=True
    if args.dma_write_limit and (args.dma_write_narrow or args.dma_write_last or args.dma_write_short):parser.error("Test factored DMA write capacity separately")
    if args.dma_write_narrow and (args.dma_write_last or args.dma_write_short):parser.error("Test DMA write narrowing separately from terminal predicates")
    if args.dma_write_short:args.dma_write_last=True
    if args.uart_zero_flags:args.uart_address_decode=True
    if args.uart_address_decode:args.uart_control=True
    if args.uart_control:args.uart_rx_fifo=True
    if args.uart_rx_fifo:args.uart_fifo=True
    uart_experiment="uart-control" if args.uart_control else "uart-rx-fifo" if args.uart_rx_fifo else "uart-fifo"
    if args.dram_row_hit or args.dram_refresh_timer or args.dram_local_ready or args.dram_parallel_chooser or args.dram_grant_onehot or args.dram_wide_command or args.dram_resetless_write or args.dram_onehot or args.dram_onehot_refresh:args.dram_write_buffer=True
    if args.dram_write_buffer:args.dram_write_capture=True
    for enabled,experiment in ((args.bus_payload,"bus-payload"),
                              (args.uart_fifo,uart_experiment)):
        if enabled:
            spec=importlib.util.spec_from_file_location(experiment,HERE.parent/experiment/"prepare.py")
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            module.prepare(out)
    if args.uart_address_decode:
        experiment=HERE.parent/"uart-address-decode"
        evidence=json.loads((ROOT/"build-uart-address-decode/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove UART address decode equivalence first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale UART address decode proof: "+name)
        assert (out/"uart.v").read_bytes()==Path(evidence["reference"]).read_bytes()
        spec=importlib.util.spec_from_file_location("uart_address_decode",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"uart.v").read_bytes()==(ROOT/"build-uart-address-decode/uart.v").read_bytes()
    if args.uart_zero_flags:
        experiment=HERE.parent/"uart-zero-flags"
        evidence=json.loads((ROOT/"build-uart-zero-flags-proved/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove UART zero flags first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                raise SystemExit("Stale UART zero-flag proof: "+name)
        assert (out/"uart.v").read_bytes()==(ROOT/"build-ddr-dma-burst-limit/uart.v").read_bytes()
        spec=importlib.util.spec_from_file_location("uart_zero_flags",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"uart.v").read_bytes()==(ROOT/"build-uart-zero-flags-proved/uart.v").read_bytes()
    if args.system_mul:
        soc=out/"synapse32_dram_soc.sv"
        original=soc.read_text()
        assert "riscv_cpu cpu (" in original
        soc.write_text(original.replace("riscv_cpu cpu (",
            "riscv_cpu #(.SYSTEM_MUL(1)) cpu (\n        .system_clk(clk),"))
    if args.dma_read_compare:
        experiment=HERE.parent/"dma-read-compare"
        evidence=json.loads((ROOT/"build-dma-read-compare/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove DMA read decision equivalence first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale DMA read comparison proof: "+name)
        spec=importlib.util.spec_from_file_location("dma_read_compare",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"axi_dma_rd.v").read_bytes()==(ROOT/"build-dma-read-compare/axi_dma_rd.v").read_bytes()
    if args.dma_read_limit:
        experiment=HERE.parent/"dma-read-limit"
        evidence=json.loads((ROOT/"build-dma-read-limit-proved/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove DMA read capacity first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale DMA read capacity proof: "+name)
        assert (out/"axi_dma_rd.v").read_bytes()==(ROOT/"build-dma-read-compare/axi_dma_rd.v").read_bytes()
        spec=importlib.util.spec_from_file_location("dma_read_limit",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"axi_dma_rd.v").read_bytes()==(ROOT/"build-dma-read-limit-proved/axi_dma_rd.v").read_bytes()
    if args.dma_write_narrow:
        experiment=HERE.parent/"dma-write-narrow"
        evidence=json.loads((ROOT/"build-dma-write-narrow-proved/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove DMA write narrowing first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale DMA write narrowing proof: "+name)
        spec=importlib.util.spec_from_file_location("dma_write_narrow",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"axi_dma_wr.v").read_bytes()==(ROOT/"build-dma-write-narrow-proved/axi_dma_wr.v").read_bytes()
    if args.dma_write_limit:
        experiment=HERE.parent/"dma-write-limit"
        evidence=json.loads((ROOT/"build-dma-write-limit-proved/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove DMA write capacity first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale DMA write capacity proof: "+name)
        spec=importlib.util.spec_from_file_location("dma_write_limit",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"axi_dma_wr.v").read_bytes()==(ROOT/"build-dma-write-limit-proved/axi_dma_wr.v").read_bytes()
    if args.dma_write_last:
        experiment=HERE.parent/"dma-write-last"
        evidence=json.loads((ROOT/"build-dma-write-last/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove DMA write last-cycle flags first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale DMA write flag proof: "+name)
        spec=importlib.util.spec_from_file_location("dma_write_last",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"axi_dma_wr.v").read_bytes()==(ROOT/"build-dma-write-last/axi_dma_wr.v").read_bytes()
    if args.dma_write_short:
        experiment=HERE.parent/"dma-write-short"
        evidence=json.loads((ROOT/"build-dma-write-short-guarded/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove direct DMA write terminal detection first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale direct DMA terminal proof: "+name)
        assert (out/"axi_dma_wr.v").read_bytes()==(ROOT/"build-dma-write-last/axi_dma_wr.v").read_bytes()
        spec=importlib.util.spec_from_file_location("dma_write_short",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
        assert (out/"axi_dma_wr.v").read_bytes()==(ROOT/"build-dma-write-short-guarded/axi_dma_wr.v").read_bytes()
    if args.boot_address_decode:
        if args.boot_local_enable:parser.error("Test boot address decode and local enable separately")
        experiment=HERE.parent/"boot-address-decode"
        evidence=json.loads((ROOT/"build-boot-address-decode/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove boot address decode equivalence first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale boot address proof: "+name)
        spec=importlib.util.spec_from_file_location("boot_address_decode",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out)
    if args.boot_local_enable:
        experiment=HERE.parent/"boot-local-enable"
        evidence=json.loads((ROOT/"build-boot-local-enable/results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove boot RAM enable equivalence first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale boot enable proof: "+name)
        reference=(ROOT/"build-boot-local-enable/candidate.sv").read_text()
        current=(out/"synapse32_dram_soc.sv").read_text()
        for key in ['wire external_address =','wire boot_address =','wire idle =','assign req_ready =','wire accept =']:
            pattern=r'^    '+re.escape(key)+r'[^;]*;'
            assert re.findall(pattern,current,re.M)==re.findall(pattern,reference,re.M),key
        spec=importlib.util.spec_from_file_location("boot_local_enable",experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.prepare(out)
    if args.uart_local_accept:
        proof_dir=args.uart_local_accept_proof.resolve()
        evidence=json.loads((proof_dir/"results.json").read_text())
        if not evidence["passed"]:raise SystemExit("Prove UART local acceptance first")
        for name,digest in evidence["sha256"].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                raise SystemExit("UART acceptance proof is stale for "+name)
        spec=importlib.util.spec_from_file_location("uart_local_accept",HERE.parent/"uart-local-accept/prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.prepare(out)
        assert (out/"synapse32_dram_soc.sv").read_bytes()==(proof_dir/"candidate.sv").read_bytes()
    if args.uart_reset_control:
        proof=ROOT/'build-uart-reset-control-proved'
        evidence=json.loads((proof/'results.json').read_text())
        assert evidence['passed']
        for name,value in evidence['sha256'].items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==value,name
        spec=importlib.util.spec_from_file_location('uart_reset_control',HERE.parent/'uart-reset-control/prepare.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.prepare(out,proof)
    if args.tpu_counters:
        spec=importlib.util.spec_from_file_location("tpu_counters",HERE.parent/tpu_experiment/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.prepare(out)
    if args.pe_valid:
        spec=importlib.util.spec_from_file_location("pe_valid",HERE.parent/"pe-valid/prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.prepare(out)
    if args.registerfile_valid:
        spec=importlib.util.spec_from_file_location("registerfile_valid",HERE.parent/"registerfile-valid/prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        (out/"registerfile.v").write_text(module.patch(module.SOURCE.read_text()))
    if args.csr_read_direct:
        spec=importlib.util.spec_from_file_location("csr_read_direct",HERE.parent/("csr-valid-decode" if args.csr_valid_decode else "csr-read-direct")/"prepare.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        (out/"csr_file.v").write_text(module.patch(module.SOURCE.read_text()))
    if args.mode=="unit":
        sources=rtl(out,dma_read_compare=args.dma_read_compare,dma_write_last=(args.dma_write_last or args.dma_write_narrow or args.dma_write_limit))+[out/"dma_fixture.sv"]
        sources += [ROOT/"multi-core"/name for name in ("tiny3tpu_axis.sv","tiny3tpu_axis_bridge.sv","tiny3tpu_axi.sv","top.v","tpu_core_wrapper.sv")]
        sources += [ROOT/"systolic_array/rtl"/name for name in ("NxN_systolic_array.v","pe.v")]
        if args.pe_valid:sources=[out/"pe.v" if p.name=="pe.v" else p for p in sources]
        if args.tpu_counters:sources=[out/"tpu_core_wrapper.sv" if p.name=="tpu_core_wrapper.sv" else p for p in sources]
        run(["verilator","--cc","--exe","--build","-j","2","-Wno-fatal","--top-module","dma_fixture", "--Mdir",out/"obj-unit",
             "-CFLAGS","-I"+str(ROOT/"tests"),*sources,ROOT/"tests/synapse32_axi_dma_test.cpp"],out/"unit-compile.log")
        run([out/"obj-unit/Vdma_fixture"],out/"unit.log")
        print((out/"unit.log").read_text(),flush=True)
    elif args.mode in ("system","stress"):
        system=out/"system"; system.mkdir(exist_ok=True)
        cpu=args.cpu_overlay_dir.resolve()
        run([sys.executable,ROOT/"tools/synapse32_system_profile.py","--out",system,
             "--cpu-overlay-dir",cpu,"--isa","rv32im","--prepare-only"],out/"profile-prepare.log")
        firmware=(ROOT/"hardware/synapse32/stream_smoke.c").read_text()
        firmware=firmware.replace('#include <stddef.h>','#include <stddef.h>\n#include "tiny3tpu_dma.h"')
        firmware=firmware.replace('    if (tiny3tpu_mmio_qgemm(&io, a, b, result, 5, 11, 7)) return 4;', '''    static tiny3tpu_dma dma={
        (volatile uint32_t *)(uintptr_t)UINT32_C(0x20003000),
        (volatile uint32_t *)(uintptr_t)UINT32_C(0x40020000),
        (volatile uint32_t *)(uintptr_t)UINT32_C(0x40022000), 256, 100000, 0};
    if (tiny3tpu_dma_init(&dma)) return 12;
    if (tiny3tpu_dma_qgemm(&dma, a, b, result, 5, 11, 7)) return 4;''')
        if args.mode=="stress":
            prefix=firmware[:firmware.index('    for (unsigned i = 0; i < 5 * 11;')]
            init=firmware[firmware.index('    static tiny3tpu_dma dma='):firmware.index('    if (tiny3tpu_dma_qgemm')]
            firmware=prefix+init+'''    static const unsigned shapes[][3]={{1,1,1},{4,8,4},{7,13,9},{8,16,8},{3,5,6}};
    for (unsigned test=0;test<5;++test) {
        unsigned m=shapes[test][0], k=shapes[test][1], n=shapes[test][2];
        for (unsigned i=0;i<m*k;++i) a[i]=(int)(i%17)-8;
        for (unsigned i=0;i<k*n;++i) b[i]=(int)(i%13)-6;
        if (tiny3tpu_dma_qgemm(&dma,a,b,result,m,k,n)) return 4;
        for (unsigned row=0;row<m;++row) for (unsigned col=0;col<n;++col) {
            int32_t expected=0;
            for (unsigned inner=0;inner<k;++inner) expected+=a[row*k+inner]*b[inner*n+col];
            if (result[row*n+col]!=expected) return 5;
            *(volatile uint32_t *)(uintptr_t)UINT32_C(0x20002004)=(uint32_t)result[row*n+col];
        }
    }
    return 0;
}
'''
        if args.mode=="stress":
            firmware=firmware.replace("{{1,1,1},{4,8,4},{7,13,9},{8,16,8},{3,5,6}}",shape_literal)
            firmware=firmware.replace("test<5;",f"test<{len(shapes)};")
        (out/"stream_smoke.c").write_text(firmware)
        cpp=(system/"profile.cpp").read_text()
        cpp=cpp.replace('#include <cstdint>','#include <cstdint>\n#include "axi_dma_memory_model.hpp"')
        cpp=cpp.replace('    std::unordered_map<uint32_t,uint32_t> memory;',
                        '    std::unordered_map<uint32_t,uint32_t> memory;\n    AxiDmaMemory axi_memory(memory);')
        cpp=cpp.replace('        dut.eval();\n        const bool accept=',
                        '        axi_memory.drive(dut);\n        dut.eval();\n        const bool accept=')
        cpp=cpp.replace('        dut.clk=1; dut.eval();',
                        '        axi_memory.capture(dut);\n        dut.clk=1; dut.eval();\n        axi_memory.commit();')
        cpp=cpp.replace('            std::cout<<"PROFILE ', '''            std::cout<<"DMA {\\"read_beats\\":"<<axi_memory.read_beats
                     <<",\\"write_beats\\":"<<axi_memory.write_beats
                     <<",\\"read_bursts\\":"<<axi_memory.read_bursts
                     <<",\\"write_bursts\\":"<<axi_memory.write_bursts<<"}\\n";
            std::cout<<"PROFILE ''')
        if args.mode=="stress":
            cpp=cpp.replace('results>=35','results>=162').replace('results!=35','results!=162')
            cpp=cpp.replace('35 signed results','162 signed results')
            cpp=cpp.replace('dram-selftest-gemm-5x11x7-v1','dram-selftest-gemm-five-shapes-v1')
            old='''            for(unsigned k=0;k<11;++k)
                expected+=(int(((results/7)*11+k)%17)-8)*(int((k*7+results%7)%13)-6);'''
            new='''            const unsigned shapes[][3]={{1,1,1},{4,8,4},{7,13,9},{8,16,8},{3,5,6}};
            unsigned local=results, shape=0;
            while(local>=shapes[shape][0]*shapes[shape][2]) {
                local-=shapes[shape][0]*shapes[shape][2]; ++shape;
            }
            const unsigned cols=shapes[shape][2], inner=shapes[shape][1];
            for(unsigned k=0;k<inner;++k)
                expected+=(int(((local/cols)*inner+k)%17)-8)*(int((k*cols+local%cols)%13)-6);'''
            assert old in cpp
            cpp=cpp.replace(old,new)
        if args.mode=="stress":
            cpp=cpp.replace("{{1,1,1},{4,8,4},{7,13,9},{8,16,8},{3,5,6}}",shape_literal)
            cpp=cpp.replace("results>=162",f"results>={result_count}").replace("results!=162",f"results!={result_count}")
            cpp=cpp.replace("162 signed results",f"{result_count} signed results")
            if args.shapes_file:
                suite_hash=hashlib.sha256(json.dumps(shapes).encode()).hexdigest()[:16]
                cpp=cpp.replace("dram-selftest-gemm-five-shapes-v1","dram-selftest-gemm-sweep-"+suite_hash)
                cpp=cpp.replace("cycle<50000000", "cycle<500000000")
        (system/"profile.cpp").write_text(cpp)
        cmake=(system/"run.cmake").read_text()
        assert "  -Os " in cmake
        cmake=cmake.replace("  -Os ","  "+args.firmware_opt+(" -DTINY3TPU_DMA_PACKED_ROWS" if args.packed_rows else "")+" ")
        for relative in ("hardware/synapse32/synapse32_dram_soc.sv", "multi-core/synapse32_tpu_peripheral.sv",
                         "multi-core/synapse32_axis_mailbox.sv","hardware/synapse32/stream_smoke.c"):
            cmake=cmake.replace('${SOURCE_DIR}/'+relative,str(out/Path(relative).name))
        cmake=cmake.replace('"${SOURCE_DIR}/src/mmio_backend.c"',
                            '"${SOURCE_DIR}/src/mmio_backend.c" "${SOURCE_DIR}/src/dma_backend.c"')
        if args.bus_payload:
            cmake=cmake.replace('${SOURCE_DIR}/hardware/synapse32/synapse32_memory_sequencer.sv',str(out/"synapse32_memory_sequencer.sv"))
        if args.uart_fifo:
            marker='file(MAKE_DIRECTORY "${BINARY_DIR}")'
            cmake=cmake.replace(marker,'list(REMOVE_ITEM cpu_modules "${SYNAPSE32_DIR}/rtl/core_modules/uart.v")\nlist(APPEND cpu_modules "'+str(out/"uart.v")+'")\n'+marker)
        cmake=cmake.replace('  ${extra_rtl}', '  ${extra_rtl}\n  '+ '\n  '.join('"'+str(p)+'"' for p in rtl(out,dma_read_compare=args.dma_read_compare,dma_write_last=(args.dma_write_last or args.dma_write_narrow or args.dma_write_limit))))
        cmake=cmake.replace('--cc --exe --build -j 2', '--cc --exe --build -j 2 -DSYNAPSE32_SYSTEM_MUL_ASSERT -CFLAGS "-I'+str(ROOT/"tests")+'"')
        if args.shapes_file:
            cmake=cmake.replace("TIMEOUT 60)","TIMEOUT 600)")
        if args.pe_valid:
            assert '${SOURCE_DIR}/systolic_array/rtl/pe.v' in cmake
            cmake=cmake.replace('${SOURCE_DIR}/systolic_array/rtl/pe.v',str(out/"pe.v"))
        if args.tpu_counters:
            assert '${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv' in cmake
            cmake=cmake.replace('${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv',str(out/"tpu_core_wrapper.sv"))
        if args.registerfile_valid:
            marker='file(MAKE_DIRECTORY "${BINARY_DIR}")'
            assert marker in cmake
            cmake=cmake.replace(marker,'list(REMOVE_ITEM cpu_modules "${SYNAPSE32_DIR}/rtl/core_modules/registerfile.v")\nlist(APPEND cpu_modules "'+str(out/"registerfile.v")+'")\n'+marker)
        if args.csr_read_direct:
            marker='file(MAKE_DIRECTORY "${BINARY_DIR}")'
            assert marker in cmake
            cmake=cmake.replace(marker,'list(REMOVE_ITEM cpu_modules "${SYNAPSE32_DIR}/rtl/core_modules/csr_file.v")\nlist(APPEND cpu_modules "'+str(out/"csr_file.v")+'")\n'+marker)
        (system/"run.cmake").write_text(cmake)
        command=["cmake","-DSOURCE_DIR="+str(ROOT),"-DBINARY_DIR="+str(system),
                 "-DSYNAPSE32_DIR="+str(ROOT.parent/"synapse32"),"-DCPU_OVERLAY_DIR="+str(cpu),
                 "-DVERILATOR=verilator","-DRISCV_GCC=riscv64-unknown-elf-gcc",
                 "-DRISCV_OBJCOPY=riscv64-unknown-elf-objcopy","-DDRAM_TEST=ON","-P",system/"run.cmake"]
        run(command,system/"run.log")
        log=(system/"run.log").read_text().splitlines()
        result={key.lower():json.loads(next(line[len(key)+1:] for line in log if line.startswith(key+' ')))
                for key in ("PROFILE","METRICS","DMA")}
        profile=result["profile"]; profile["cpu_ipc"]=profile["instructions"]/profile["cpu_edges"]
        paths=accelerator_rtl()+rtl(out,dma_read_compare=args.dma_read_compare,dma_write_last=(args.dma_write_last or args.dma_write_narrow or args.dma_write_limit))+list(out.glob("*.sv"))+list(out.glob("*.c"))+list(cpu.glob("*.v"))
        if args.uart_zero_flags:
            paths += [ROOT/"build-uart-zero-flags-proved/results.json",HERE.parent/"uart-zero-flags/prepare.py",HERE.parent/"uart-zero-flags/prove.py"]
        if args.uart_reset_control:
            paths += [ROOT/'build-uart-reset-control-proved/results.json',HERE.parent/'uart-reset-control/prepare.py',HERE.parent/'uart-reset-control/prove.py']
        if args.uart_local_accept:
            paths += [args.uart_local_accept_proof.resolve()/"results.json",HERE.parent/"uart-local-accept/prepare.py",HERE.parent/"uart-local-accept/prove.py"]
        paths += [Path(__file__),HERE/"prepare.py",ROOT/"tools/synapse32_system_profile.py",ROOT/"src/dma_backend.c",
                  ROOT/"include/tiny3tpu_dma.h",ROOT/"tests/axi_dma_memory_model.hpp",system/"profile.cpp",
                  system/"run.cmake",system/"smoke.elf",system/"smoke.bin"]
        if args.boot_local_enable:
            paths += [ROOT/"build-boot-local-enable/results.json",HERE.parent/"boot-local-enable/prepare.py",HERE.parent/"boot-local-enable/prove.py"]
        if args.dma_read_compare:
            paths += [ROOT/"build-dma-read-compare/results.json",HERE.parent/"dma-read-compare/prepare.py",HERE.parent/"dma-read-compare/prove.py"]
        if args.dma_read_limit:
            paths += [ROOT/"build-dma-read-limit-proved/results.json",HERE.parent/"dma-read-limit/prepare.py",HERE.parent/"dma-read-limit/prove.py"]
        if args.dma_write_narrow:
            paths += [ROOT/"build-dma-write-narrow-proved/results.json",HERE.parent/"dma-write-narrow/prepare.py",HERE.parent/"dma-write-narrow/prove.py"]
        if args.dma_write_limit:
            paths += [ROOT/"build-dma-write-limit-proved/results.json",HERE.parent/"dma-write-limit/prepare.py",HERE.parent/"dma-write-limit/prove.py"]
        if args.dma_write_last:
            paths += [ROOT/"build-dma-write-last/results.json",HERE.parent/"dma-write-last/prepare.py",HERE.parent/"dma-write-last/prove.py"]
        if args.dma_write_short:
            paths += [ROOT/"build-dma-write-short-guarded/results.json",HERE.parent/"dma-write-short/prepare.py",HERE.parent/"dma-write-short/prove.py"]
        if args.pe_valid:paths+=[out/"pe.v"]
        if args.uart_fifo:paths+=[out/"uart.v"]
        if args.registerfile_valid:paths+=[out/"registerfile.v"]
        if args.csr_read_direct:paths+=[out/"csr_file.v"]
        result["sha256"]={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        result["command"]=list(map(str,command))
        result["configuration"]={"system_mul":args.system_mul,"firmware_opt":args.firmware_opt,"packed_rows":args.packed_rows,
            "dram_command_buffer_board_only":args.dram_command_buffer,
            "dram_write_capture_board_only":args.dram_write_capture,
            "dram_write_buffer_board_only":args.dram_write_buffer,
            "dram_row_hit_board_only":args.dram_row_hit,"wb_decode_board_only":args.wb_decode,"wb_active_board_only":args.wb_active,"uart_reset_control":args.uart_reset_control,"uart_local_accept":args.uart_local_accept,"uart_local_accept_proof":str(args.uart_local_accept_proof.resolve()) if args.uart_local_accept else None,"boot_local_enable":args.boot_local_enable,"dma_read_limit":args.dma_read_limit,"dma_read_compare":args.dma_read_compare,"tpu_counters":args.tpu_counters,"pe_valid":args.pe_valid,"tpu_feed_decode":args.tpu_feed_decode,"tpu_spm_valid":args.tpu_spm_valid,"registerfile_valid":args.registerfile_valid,"csr_read_direct":args.csr_read_direct,"csr_valid_decode":args.csr_valid_decode,"dram_refresh_timer_board_only":args.dram_refresh_timer,"dram_local_ready_board_only":args.dram_local_ready,"dram_parallel_chooser_board_only":args.dram_parallel_chooser,"dram_grant_onehot_board_only":args.dram_grant_onehot,"dram_wide_command_board_only":args.dram_wide_command,"dram_resetless_write_board_only":args.dram_resetless_write,"dram_onehot_board_only":args.dram_onehot,"dram_onehot_refresh_board_only":args.dram_onehot_refresh,
            "bus_payload":args.bus_payload,"uart_fifo":args.uart_fifo,
            "uart_rx_fifo":args.uart_rx_fifo,
            "uart_zero_flags":args.uart_zero_flags,"uart_control":args.uart_control,"uart_address_decode":args.uart_address_decode,"boot_address_decode":args.boot_address_decode,"dma_write_limit":args.dma_write_limit,"dma_write_narrow":args.dma_write_narrow,"dma_write_last":args.dma_write_last,"dma_write_short":args.dma_write_short,
            "litedram_frontend_simulated":False,"gemm_shapes":shapes}
        (system/"results.json").write_text(json.dumps(result,indent=2)+'\n')
        print(f"PASS DMA RV32IM CPU + DDR model + TPU: {profile['instructions']} instructions / {profile['cpu_edges']} CPU edges = {profile['cpu_ipc']:.6f} IPC; {result['metrics']['system_cycles']} system cycles",flush=True)
        print(result["dma"],flush=True)
    elif args.mode=="synth":
        if not (out/"system/results.json").exists():
            raise SystemExit("Run system validation in this output directory before board synthesis")
        validated=json.loads((out/"system/results.json").read_text())
        if validated["configuration"].get("firmware_opt","-Os")!=args.firmware_opt:
            raise SystemExit("System validation uses a different firmware optimization level")
        if validated["configuration"].get("packed_rows",False)!=args.packed_rows:
            raise SystemExit("System validation uses a different packed-row firmware setting")
        verified=validated["sha256"]
        checked=accelerator_rtl()+rtl(out,dma_read_compare=args.dma_read_compare,dma_write_last=(args.dma_write_last or args.dma_write_narrow or args.dma_write_limit))+list(args.cpu_overlay_dir.resolve().glob("*.v"))+[out/"synapse32_dram_soc.sv",out/"stream_smoke.c",
                    ROOT/"src/dma_backend.c",ROOT/"include/tiny3tpu_dma.h"]
        if args.bus_payload:checked+=[out/"synapse32_memory_sequencer.sv"]
        if args.uart_fifo:checked+=[out/"uart.v"]
        if args.tpu_counters:checked+=[out/"tpu_core_wrapper.sv"]
        if args.pe_valid:checked+=[out/"pe.v"]
        if args.registerfile_valid:checked+=[out/"registerfile.v"]
        if args.csr_read_direct:checked+=[out/"csr_file.v"]
        for path in checked:
            if verified.get(str(path))!=hashlib.sha256(path.read_bytes()).hexdigest():
                raise SystemExit("System validation is stale for "+str(path))
        if args.dram_command_buffer:
            proof=ROOT/"build-ddr-command-buffer/unit-512/results.json"
            if not proof.exists():
                raise SystemExit("Validate the buffered LiteDRAM converter, including 32-to-512 traffic, first")
            evidence=json.loads(proof.read_text())
            if not evidence["passed"] or not evidence.get("native_write_deadline"):
                raise SystemExit("Validate the buffered converter against scheduled native writes first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("DDR command buffer validation is stale for "+name)
        if args.dram_write_capture:
            proof=ROOT/"build-ddr-write-capture-final/results.json"
            evidence=json.loads(proof.read_text())
            if not evidence["passed"] or not evidence.get("native_write_deadline"):
                raise SystemExit("Validate the DDR write capture candidate first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("DDR write capture validation is stale for "+name)
        if args.dram_write_buffer:
            evidence=json.loads((ROOT/"build-ddr-write-buffer/results.json").read_text())
            if not evidence["passed"] or not evidence.get("native_write_deadline"):
                raise SystemExit("Validate the two-entry DDR write buffer first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("DDR write buffer validation is stale for "+name)
        if args.dram_row_hit:
            for folder,board_settings in (("build-ddr-row-hit",False),("build-ddr-row-hit-board",True)):
                evidence=json.loads((ROOT/folder/"results.json").read_text())
                if not evidence["passed"] or evidence.get("board_settings")!=board_settings:
                    raise SystemExit("Validate bank row-hit equivalence for both geometries first")
                for name,digest in evidence["sha256"].items():
                    if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                        raise SystemExit("Bank row-hit validation is stale for "+name)
        if args.uart_fifo:
            proof=ROOT/("build-ddr-"+uart_experiment)/"results.json"
            evidence=json.loads(proof.read_text())
            uart_reference=out/"uart.v"
            if args.uart_address_decode:
                # The exact candidate and every decode-proof hash were checked
                # above. Compose that proof with the existing UART state proof.
                decode_proof=json.loads((ROOT/"build-uart-address-decode/results.json").read_text())
                uart_reference=Path(decode_proof["reference"])
            if not evidence["passed"] or hashlib.sha256(uart_reference.read_bytes()).hexdigest()!=evidence["sha256"][str(proof.parent/"uart.v")]:
                raise SystemExit("UART FIFO candidate must match its passing proof")
        if args.bus_payload:
            proof=ROOT/"build-ddr-bus-payload/proof/proof-sources.json"
            evidence=json.loads(proof.read_text())
            if hashlib.sha256((out/"synapse32_memory_sequencer.sv").read_bytes()).hexdigest()!=evidence[str(ROOT/"build-ddr-bus-payload/synapse32_memory_sequencer.sv")]:
                raise SystemExit("Bus payload candidate must match its passing proof")
        if args.wb_decode:
            evidence=json.loads((ROOT/"build-ddr-wb-decode/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Prove Wishbone decode equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Wishbone decode proof is stale for "+name)
        if args.wb_active:
            evidence=json.loads((ROOT/"build-ddr-wb-active/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Prove Wishbone decode equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Wishbone decode proof is stale for "+name)
        if args.dram_refresh_timer:
            evidence=json.loads((ROOT/"build-ddr-refresh-timer/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Prove Refresh timer equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Refresh timer proof is stale for "+name)
        if args.dram_parallel_chooser and args.dram_refresh_timer:
            evidence=json.loads((ROOT/"build-ddr-parallel-timer/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Verify composed selector/timer first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Composed selector/timer proof is stale for "+name)
        if args.dram_grant_onehot and args.dram_refresh_timer:
            evidence=json.loads((ROOT/"build-ddr-grant-timer/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Verify composed selector/timer first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Composed selector/timer proof is stale for "+name)
        if args.dram_local_ready:
            evidence=json.loads((ROOT/"build-ddr-local-ready/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Prove Command chooser equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Command chooser proof is stale for "+name)
        if args.dram_parallel_chooser:
            evidence=json.loads((ROOT/"build-ddr-parallel-chooser/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Prove Parallel chooser equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Parallel chooser proof is stale for "+name)
        if args.dram_grant_onehot:
            evidence=json.loads((ROOT/"build-ddr-parallel-chooser/results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Prove One-hot grant chooser equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("One-hot grant chooser proof is stale for "+name)
        if args.dram_onehot:
            evidence=json.loads((ROOT/"build-ddr-onehot-explicit-bank/results.json").read_text())
            if not evidence["passed"] or not evidence.get("board_settings"): raise SystemExit("Prove One-hot bank FSM equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("One-hot bank FSM proof is stale for "+name)
        if args.dram_onehot_refresh:
            evidence=json.loads((ROOT/"build-ddr-onehot-refresh/results.json").read_text())
            if not evidence["passed"] or not evidence.get("board_settings"): raise SystemExit("Prove One-hot refresher FSM equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("One-hot refresher FSM proof is stale for "+name)
        if args.dram_wide_command:
            evidence=json.loads((ROOT/"build-ddr-wide-command/results.json").read_text())
            if not evidence["passed"] or not evidence.get("native_write_deadline"): raise SystemExit("Prove Wide command equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Wide command proof is stale for "+name)
        if args.dram_resetless_write:
            evidence=json.loads((ROOT/"build-ddr-resetless-write/results.json").read_text())
            if not evidence["passed"] or not evidence.get("native_write_deadline"): raise SystemExit("Prove Resetless wide write equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("Resetless wide write proof is stale for "+name)
        if args.uart_local_accept:
            evidence=json.loads((args.uart_local_accept_proof.resolve()/"results.json").read_text())
            if not evidence["passed"]: raise SystemExit("Prove UART local acceptance first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:
                    raise SystemExit("UART acceptance proof is stale for "+name)
            assert (out/"synapse32_dram_soc.sv").read_bytes()==((ROOT/'build-uart-reset-control-proved/synapse32_dram_soc.sv') if args.uart_reset_control else (args.uart_local_accept_proof.resolve()/"candidate.sv")).read_bytes()
        if args.pe_valid:
            evidence=json.loads((ROOT/"build-pe-valid/results.json").read_text())
            if not evidence["passed"]:raise SystemExit("Prove PE accumulator reset ownership first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale PE proof: "+name)
            assert (out/"pe.v").read_bytes()==(ROOT/"build-pe-valid/pe.v").read_bytes()
        if args.tpu_counters:
            evidence=json.loads((ROOT/tpu_evidence/"results.json").read_text())
            if not evidence["passed"] or evidence["n"]!=4:raise SystemExit("Prove current TPU counter bounds first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale TPU counter proof: "+name)
        if args.registerfile_valid:
            evidence=json.loads((ROOT/"build-registerfile-valid/results.json").read_text())
            if not evidence["passed"]:raise SystemExit("Prove register-file ownership first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale register-file proof: "+name)
        if args.csr_read_direct:
            evidence_dir=ROOT/("build-csr-valid-decode" if args.csr_valid_decode else "build-csr-read-direct")
            evidence=json.loads((evidence_dir/"results.json").read_text())
            if not evidence["passed"]:raise SystemExit("Prove CSR read equivalence first")
            for name,digest in evidence["sha256"].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise SystemExit("Stale CSR read proof: "+name)
            assert (out/"csr_file.v").read_bytes()==(evidence_dir/"candidate.v").read_bytes()
        board_sources(out, system_mul=args.system_mul, dram_command_buffer=args.dram_command_buffer,
                      bus_payload=args.bus_payload,uart_fifo=args.uart_fifo,
                      dram_write_capture=args.dram_write_capture,dram_write_buffer=args.dram_write_buffer,
                      dram_row_hit=args.dram_row_hit,firmware_opt=args.firmware_opt,packed_rows=args.packed_rows,wb_decode=args.wb_decode,wb_active=args.wb_active,dram_refresh_timer=args.dram_refresh_timer,dram_local_ready=args.dram_local_ready,dram_parallel_chooser=args.dram_parallel_chooser,dram_grant_onehot=args.dram_grant_onehot,dram_wide_command=args.dram_wide_command,tpu_counters=args.tpu_counters,pe_valid=args.pe_valid,dma_read_compare=args.dma_read_compare,dma_write_last=(args.dma_write_last or args.dma_write_narrow or args.dma_write_limit),registerfile_valid=args.registerfile_valid,csr_read_direct=args.csr_read_direct,dram_resetless_write=args.dram_resetless_write,dram_onehot=args.dram_onehot,dram_onehot_refresh=args.dram_onehot_refresh)
        run([ROOT/".venv-ddr-compat/bin/python",out/"board_build.py","synth",
             "--synapse32-dir",ROOT.parent/"synapse32","--cpu-overlay-dir",args.cpu_overlay_dir.resolve(),
             "--build-dir",out/"board"],out/"synth-console.log")
    elif args.mode=="route":
        board=out/"board"
        tool=Path("/tmp/tiny3tpu-nextpnr-current/build/nextpnr-xilinx")
        chipdb=Path("/tmp/tiny3tpu-nextpnr-current/kc705.bin")
        command=[tool,"--chipdb",chipdb,"--xdc",board/"kc705.xdc","--freq","100","--seed",str(args.seed),
                 "--json",board/"soc.json","--write",board/"routed.json","--report",board/"report.json","--log",board/"route.log"]
        paths=accelerator_rtl()+rtl(out,dma_read_compare=args.dma_read_compare,dma_write_last=(args.dma_write_last or args.dma_write_narrow or args.dma_write_limit))+list(out.glob("*.sv"))+[tool,chipdb,board/"kc705.xdc",board/"soc.json",board/"synth.ys",board/"firmware.hex"]
        paths+=list(args.cpu_overlay_dir.resolve().glob("*.v"))
        paths+=list(out.glob("*.py"))+list(out.glob("*.yml"))
        if args.boot_local_enable:
            paths += [ROOT/"build-boot-local-enable/results.json",HERE.parent/"boot-local-enable/prepare.py",HERE.parent/"boot-local-enable/prove.py"]
        if args.boot_address_decode:
            paths += [ROOT/"build-boot-address-decode/results.json",HERE.parent/"boot-address-decode/prepare.py",HERE.parent/"boot-address-decode/prove.py"]
        if args.dma_read_compare:
            paths += [ROOT/"build-dma-read-compare/results.json",HERE.parent/"dma-read-compare/prepare.py",HERE.parent/"dma-read-compare/prove.py"]
        if args.dma_read_limit:
            paths += [ROOT/"build-dma-read-limit-proved/results.json",HERE.parent/"dma-read-limit/prepare.py",HERE.parent/"dma-read-limit/prove.py"]
        if args.dma_write_narrow:
            paths += [ROOT/"build-dma-write-narrow-proved/results.json",HERE.parent/"dma-write-narrow/prepare.py",HERE.parent/"dma-write-narrow/prove.py"]
        if args.dma_write_limit:
            paths += [ROOT/"build-dma-write-limit-proved/results.json",HERE.parent/"dma-write-limit/prepare.py",HERE.parent/"dma-write-limit/prove.py"]
        if args.dma_write_last:
            paths += [ROOT/"build-dma-write-last/results.json",HERE.parent/"dma-write-last/prepare.py",HERE.parent/"dma-write-last/prove.py"]
        if args.dma_write_short:
            paths += [ROOT/"build-dma-write-short-guarded/results.json",HERE.parent/"dma-write-short/prepare.py",HERE.parent/"dma-write-short/prove.py"]
        if args.uart_address_decode:
            paths += [ROOT/"build-uart-address-decode/results.json",HERE.parent/"uart-address-decode/prepare.py",HERE.parent/"uart-address-decode/prove.py"]
        if args.pe_valid:paths+=[out/"pe.v"]
        if args.uart_fifo:paths+=[out/"uart.v"]
        paths+=[ROOT/"tools/synapse32_timing_report.py"]
        paths+=list((board/"litedram/command-buffer-evidence").glob("*"))
        paths+=list(p for p in (board/"litedram/write-capture-evidence").rglob("*") if p.is_file())
        paths+=list(p for p in (board/"litedram/write-buffer-evidence").rglob("*") if p.is_file())
        paths+=list(p for p in (board/"litedram/row-hit-evidence").rglob("*") if p.is_file())
        if args.wb_decode:
            paths += [ROOT/"build-ddr-wb-decode/results.json",HERE.parent/"wb-decode/prepare.py",HERE.parent/"wb-decode/prove.py"]
        if args.wb_active:
            paths += [ROOT/"build-ddr-wb-active/results.json",HERE.parent/"wb-active/prepare.py",HERE.parent/"wb-active/prove.py"]
        if args.dram_refresh_timer:
            paths += [ROOT/"build-ddr-refresh-timer/results.json",HERE.parent/"dram-refresh-timer/generate.py",HERE.parent/"dram-refresh-timer/check.py"]
            paths += list((board/"litedram/refresh-timer-evidence").glob("*"))
        if args.dram_local_ready:
            paths += [ROOT/"build-ddr-local-ready/results.json",HERE.parent/"dram-local-ready/generate.py",HERE.parent/"dram-local-ready/check.py"]
            paths += list((board/"litedram/local-ready-evidence").glob("*"))
        if args.dram_wide_command:
            paths += [ROOT/"build-ddr-wide-command/results.json",HERE.parent/"dram-wide-command/generate.py",HERE.parent/"dram-wide-command/verify.py"]
            paths += list((board/"litedram/wide-command-evidence").glob("*"))
        if args.dram_resetless_write:
            paths += [ROOT/"build-ddr-resetless-write/results.json",HERE.parent/"dram-resetless-write/generate.py",HERE.parent/"dram-resetless-write/verify.py"]
            paths += list((board/"litedram/resetless-write-evidence").glob("*"))
        if args.uart_zero_flags:
            paths += [ROOT/"build-uart-zero-flags-proved/results.json",HERE.parent/"uart-zero-flags/prepare.py",HERE.parent/"uart-zero-flags/prove.py"]
        if args.uart_reset_control:
            paths += [ROOT/'build-uart-reset-control-proved/results.json',HERE.parent/'uart-reset-control/prepare.py',HERE.parent/'uart-reset-control/prove.py']
        if args.uart_local_accept:
            paths += [args.uart_local_accept_proof.resolve()/"results.json",HERE.parent/"uart-local-accept/prepare.py",HERE.parent/"uart-local-accept/prove.py"]
        if args.registerfile_valid:
            paths += [out/"registerfile.v",ROOT/"build-registerfile-valid/results.json",HERE.parent/"registerfile-valid/prepare.py",HERE.parent/"registerfile-valid/prove.py"]
        if args.csr_read_direct:
            experiment="csr-valid-decode" if args.csr_valid_decode else "csr-read-direct"
            paths += [out/"csr_file.v",ROOT/("build-"+experiment)/"results.json",HERE.parent/experiment/"prepare.py",HERE.parent/experiment/"prove.py"]
        if args.pe_valid:
            paths += [out/"pe.v",ROOT/"build-pe-valid/results.json",HERE.parent/"pe-valid/prepare.py",HERE.parent/"pe-valid/prove.py"]
        if args.tpu_counters:
            experiment=tpu_experiment
            evidence=tpu_evidence
            paths += [ROOT/evidence/"results.json",HERE.parent/experiment/"prepare.py",HERE.parent/experiment/"prove.py"]
        if args.dram_onehot:
            paths += [ROOT/"build-ddr-onehot-explicit-bank/results.json",HERE.parent/"dram-onehot/generate.py",HERE.parent/"dram-onehot/check.py"]
            paths += list((board/"litedram/onehot-evidence").glob("*"))
        if args.dram_onehot_refresh:
            paths += [ROOT/"build-ddr-onehot-refresh/results.json",HERE.parent/"dram-onehot-refresh/generate.py",HERE.parent/"dram-onehot-refresh/check.py"]
            paths += list((board/"litedram/onehot-evidence").glob("*"))
        if args.dram_parallel_chooser:
            paths += [ROOT/"build-ddr-parallel-chooser/results.json",HERE.parent/"dram-parallel-chooser/generate.py",HERE.parent/"dram-parallel-chooser/check.py"]
            paths += list((board/"litedram/parallel-chooser-evidence").glob("*"))
        if args.dram_grant_onehot:
            paths += [ROOT/"build-ddr-grant-onehot/results.json",HERE.parent/"dram-grant-onehot/generate.py",HERE.parent/"dram-grant-onehot/check.py",HERE.parent/"dram-parallel-chooser/generate.py"]
            paths += [p for p in (board/"litedram/grant-onehot-evidence").rglob("*") if p.is_file()]
        if args.dram_parallel_chooser and args.dram_refresh_timer:
            paths += [ROOT/"build-ddr-parallel-timer/results.json",HERE.parent/"dram-parallel-timer/generate.py",HERE.parent/"dram-parallel-timer/verify.py"]
        if args.dram_grant_onehot and args.dram_refresh_timer:
            paths += [ROOT/"build-ddr-grant-timer/results.json",HERE.parent/"dram-grant-timer/generate.py",HERE.parent/"dram-grant-timer/verify.py"]
        manifest={"command":list(map(str,command)),"seed":args.seed,
                  "sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
        (board/"route-manifest.json").write_text(json.dumps(manifest,indent=2)+'\n')
        with (board/"route-console.log").open('w') as log:
            rc=subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT).returncode
        sys.path.insert(0,str(ROOT))
        from tools.synapse32_timing_report import summarize
        manifest["timing"]=summarize((board/"route.log").read_text(),exit_code=rc)
        (board/"route-manifest.json").write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps(manifest["timing"]["final_clocks"],indent=2),flush=True)
        if not manifest["timing"]["accepted"]:
            raise SystemExit("REJECTED: "+str(manifest["timing"]["reasons"]))


if __name__=="__main__":main()
