`timescale 1ns/1ps
module cpu_tb;
    parameter GATED = 1;
    reg clk=0, rst=1;
    always #5 clk=~clk;
    wire cpu_clk, step;
    wire [31:0] pc, instr, rdata, rdaddr, wraddr, wdata;
    wire rden, wren;
    wire [3:0] strb;
    wire [2:0] load_type;
    wire fault, req_valid, req_ready, req_write, resp_ready;
    wire [31:0] req_addr, req_data;
    wire [3:0] req_strb;
    reg resp_valid=0;
    reg [31:0] resp_data=0;
    reg [31:0] rom[0:32767];
    reg [31:0] expected[0:8191];
    reg [31:0] regs[0:31];
    reg [31:0] div_expected[0:32767];
    reg div_present[0:32767];
    integer n=0, stores=0, seen=0, cycles=0, edges=0;
    integer launched=0, retired=0, written=0, divisions=0;
    integer delay_left=0;
    reg pending=0;
    reg [31:0] held_pc, held_id_pc;
    reg previous_wait=0;
    reg timer_irq=0;
    integer interrupts=0;
    integer data_reads=0;
    reg [31:0] interrupted_pc;
    reg [31:0] corners[0:11];
    reg [31:0] rng=32'h521afe09;
    integer i,j,k,pass;

    riscv_cpu cpu (
        .clk(cpu_clk), .rst(rst), .module_instr_in(instr),
        .module_read_data_in(rdata), .module_pc_out(pc),
        .module_wr_data_out(wdata), .module_mem_wr_en(wren),
        .module_mem_rd_en(rden), .module_read_addr(rdaddr),
        .module_write_addr(wraddr), .module_write_byte_enable(strb),
        .module_load_type(load_type), .module_load_page_fault_in(1'b0),
        .module_store_page_fault_in(1'b0), .module_page_fault_addr_in(32'b0),
        .module_instr_page_fault_in(1'b0),
        .module_data_mmu_enable_out(), .module_data_privilege_out(),
        .module_satp_out(), .module_data_sum_out(), .module_data_mxr_out(),
        .module_instr_mmu_enable_out(), .module_instr_privilege_out(),
        .timer_interrupt(timer_irq), .software_interrupt(1'b0), .external_interrupt(1'b0)
    );
    generate if (GATED) begin
        synapse32_clock_enable gate(.clk(clk), .enable(rst || step), .cpu_clk(cpu_clk));
        synapse32_memory_sequencer seq (
            .clk(clk), .rst(rst), .ready_to_run(!rst),
            .cpu_pc(pc), .cpu_rd_en(rden), .cpu_wr_en(wren),
            .cpu_rd_addr(rdaddr), .cpu_wr_addr(wraddr), .cpu_wdata(wdata),
            .cpu_wstrb(strb), .cpu_load_type(load_type),
            .cpu_instr(instr), .cpu_rdata(rdata), .cpu_step(step), .fault(fault),
            .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
            .req_addr(req_addr), .req_wdata(req_data), .req_wstrb(req_strb),
            .resp_valid(resp_valid), .resp_ready(resp_ready),
            .resp_rdata(resp_data), .resp_error(1'b0)
        );
    end else begin
        assign cpu_clk=clk;
        assign instr=fetch(pc);
        assign rdata=32'hffffff9b;
        assign fault=0;
        assign req_valid=0;
    end endgenerate

    function automatic [31:0] fetch(input [31:0] address);
        if (address >= 32'h80000000 && address < 32'h80020000)
            fetch=rom[(address-32'h80000000)>>2];
        else begin
            $fatal(1,"unexpected fetch %h",address);
            fetch=0;
        end
    endfunction
    function automatic [31:0] reference_div(input [31:0] a,b, input integer op);
        reg signed [63:0] sa,sb;
        begin
            sa={{32{a[31]}},a}; sb={{32{b[31]}},b};
            if(b==0) reference_div=(op>=6)?a:32'hffffffff;
            else case(op)
                4: reference_div=sa/sb;
                5: reference_div={32'b0,a}/{32'b0,b};
                6: reference_div=sa%sb;
                7: reference_div={32'b0,a}%{32'b0,b};
            endcase
        end
    endfunction
    task emit(input [31:0] ins);
        begin rom[n]=ins; n=n+1; end
    endtask
    task li(input integer rd,input [31:0] value);
        reg [31:0] hi;
        begin
            hi=(value+32'h800)&32'hfffff000;
            emit(hi | (rd<<7) | 32'h37);
            emit(((value&32'hfff)<<20)|(rd<<15)|(rd<<7)|32'h13);
            regs[rd]=value;
        end
    endtask
    task divide(input integer op,rd,a,b);
        begin
            div_present[n]=1;
            div_expected[n]=reference_div(regs[a],regs[b],op);
            regs[rd]=div_expected[n]; regs[0]=0;
            emit(32'h02000033|(b<<20)|(a<<15)|(op<<12)|(rd<<7));
            divisions=divisions+1;
        end
    endtask
    task save(input integer rd);
        begin
            // A fixed MMIO-like address: every store is independently counted.
            emit((rd<<20)|(20<<15)|32'h2023);
            expected[stores]=regs[rd]; stores=stores+1;
        end
    endtask
    task check_store(input [31:0] address,value,input [3:0] enables);
        begin
            if(address!==32'h10000000 || enables!==15 || seen>=stores)
                $fatal(1,"unexpected/duplicate store #%0d addr=%h mask=%h",seen,address,enables);
            if(value!==expected[seen])
                $fatal(1,"store #%0d got=%h expected=%h pc=%h",seen,value,expected[seen],pc);
            seen=seen+1;
        end
    endtask
    assign req_ready=!pending && !resp_valid && (cycles%5 != 0);
    always @(posedge clk) begin
        if(rst) begin
            pending<=0; resp_valid<=0; delay_left<=0; cycles<=0;
        end else begin
            cycles<=cycles+1;
            if(fault) $fatal(1,"sequencer fault");
            if(cycles>2000000) $fatal(1,"timeout seen=%0d/%0d pc=%h",seen,stores,pc);
            if(GATED && req_valid && req_ready) begin
                if(req_write) begin
                    check_store(req_addr,req_data,req_strb);
                    resp_data<=0;
                end else if(req_addr==32'h10010000) begin
                    resp_data<=32'hffffff9b;
                    data_reads=data_reads+1;
                end
                else resp_data<=fetch(req_addr);
                pending<=1; delay_left<=1+(cycles%7);
            end
            if(pending) begin
                if(delay_left==0) begin pending<=0; resp_valid<=1; end
                else delay_left<=delay_left-1;
            end
            if(resp_valid && resp_ready) resp_valid<=0;
        end
    end
    always @(posedge cpu_clk) begin
        if(rst) begin
            seen=0; edges=0; launched=0; retired=0; written=0; previous_wait=0; interrupts=0; data_reads=0;
        end else begin
            edges=edges+1;
            if(!GATED && wren) check_store(wraddr,wdata,strb);
            if(!GATED && rden) begin
                if(rdaddr!==32'h10010000) $fatal(1,"unexpected load address");
                data_reads=data_reads+1;
            end
            if(previous_wait && (pc!==held_pc || cpu.id_ex_inst0_pc_out!==held_id_pc))
                $fatal(1,"front pipeline moved while divider waiting");
            previous_wait=cpu.div_wait && !cpu.pipeline_flush;
            held_pc=pc; held_id_pc=cpu.id_ex_inst0_pc_out;
            if(cpu.div_start) launched=launched+1;
            if(cpu.interrupt_taken_qualified) begin
                if(!cpu.div_busy) $fatal(1,"interrupt missed active divide");
                interrupted_pc=cpu.id_ex_inst0_pc_out;
                interrupts=interrupts+1;
            end
            if(cpu.div_wait && cpu.instret_increment)
                $fatal(1,"divider retired while waiting");
            if(cpu.div_instruction && cpu.instret_increment) retired=retired+1;
            if(cpu.mem_wb_inst0_pc_out>=32'h80000000 &&
               cpu.mem_wb_inst0_pc_out<32'h80020000 &&
               div_present[(cpu.mem_wb_inst0_pc_out-32'h80000000)>>2] &&
               cpu.mem_wb_inst0_rd_valid_out) begin
                if(cpu.wb_inst0_rd_value_out !== div_expected[(cpu.mem_wb_inst0_pc_out-32'h80000000)>>2])
                    $fatal(1,"divide WB mismatch pc=%h got=%h",cpu.mem_wb_inst0_pc_out,cpu.wb_inst0_rd_value_out);
                written=written+1;
            end
        end
    end
    initial begin
        for(i=0;i<32768;i=i+1) begin rom[i]=32'h00000013; div_present[i]=0; end
        for(i=0;i<32;i=i+1) regs[i]=0;
        corners[0]=0; corners[1]=1; corners[2]=32'hffffffff;
        corners[3]=32'h80000000; corners[4]=32'h7fffffff;
        corners[5]=2; corners[6]=32'hfffffffe; corners[7]=3;
        corners[8]=32'hfffffffd; corners[9]=32'h80000001;
        corners[10]=32'h55555555; corners[11]=32'haaaaaaaa;
        li(20,32'h10000000); li(21,32'h10010000);
        // Real CSR instructions enable a machine timer interrupt; handler MRET
        // retries the canceled divide without changing architectural operands.
        li(22,32'h8001f000); emit(32'h305b1073);
        li(22,32'h80); emit(32'h304b1073);
        li(22,32'h8); emit(32'h300b1073);
        rom[31744]=32'h30200073;
        for(i=0;i<12;i=i+1) for(j=0;j<12;j=j+1) begin
            li(1,corners[i]); li(2,corners[j]);
            save(1); // Older store sits in MEM at divider launch.
            for(k=4;k<8;k=k+1) divide(k,k,1,2);
            for(k=4;k<8;k=k+1) save(k);
            divide(4,8,4,2); divide(7,9,8,5); // dependent back-to-back
            save(8); save(9);
            emit((8<<20)|(9<<15)|(10<<7)|32'h33); // dependent ADD
            regs[10]=regs[8]+regs[9]; save(10);
        end
        for(i=0;i<200;i=i+1) begin
            rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5);
            li(1,rng);
            rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5);
            li(2,rng);
            divide(4+(i%4),3,1,2); save(3);
        end
        // Immediate load-use -> divide, result -> store, rd aliases source.
        emit((21<<15)|(1<<7)|32'h2003); regs[1]=32'hffffff9b;
        divide(4,1,1,2); save(1);
        divide(6,0,1,2); save(0); // x0 destination still executes.
        // Taken dependent branch squashes a wrong-path divide and store.
        divide(5,3,1,2);
        emit((3<<20)|(3<<15)|32'h663); // beq x3,x3,+12
        emit(32'h0220c1b3); emit((1<<20)|(20<<15)|32'h2023);
        save(3);
        emit(32'h0000006f);
        repeat(5) @(negedge clk); rst=0;
        // Reset during actual CPU division, then restart from reset vector.
        wait(cpu.div_busy); repeat(5) @(negedge cpu_clk);
        @(negedge clk); rst=1;
        repeat(5) @(negedge clk); rst=0;
        wait(cpu.div_busy);
        repeat(5) @(negedge cpu_clk);
        timer_irq=1;
        wait(interrupts==1);
        @(negedge cpu_clk); timer_irq=0;
        if(cpu.div_busy || cpu.div_done) $fatal(1,"cancel did not clear divider");
        if(cpu.csr_file_inst.mepc!==interrupted_pc)
            $fatal(1,"interrupt resume PC mismatch");
        wait(seen==stores);
        repeat(150) @(negedge cpu_clk);
        if(launched!=divisions+1 || retired!=divisions || written!=divisions || interrupts!=1)
            $fatal(1,"count mismatch launch=%0d retire=%0d WB=%0d expected=%0d",
                   launched,retired,written,divisions);
        if(data_reads!=1) $fatal(1,"duplicate/missing data reads %0d",data_reads);
        $display("PASS GATED=%0d instructions=%0d divides=%0d stores=%0d loads=%0d launches=%0d retires=%0d WB=%0d interrupts=%0d CPU_edges=%0d system_cycles=%0d reset-mid-divide",
                 GATED,n,divisions,seen,data_reads,launched,retired,written,interrupts,edges,cycles);
        $finish;
    end
endmodule
