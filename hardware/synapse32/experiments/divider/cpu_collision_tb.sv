`timescale 1ns/1ps
// Actual CPU boundary tests. Only external interrupt/fault inputs are driven;
// hierarchy is observed for exact edge coverage, never forced or deposited.
module cpu_collision_tb;
    parameter GATED=1;
    reg clk=0, rst=1;
    always #5 clk=~clk;
    wire cpu_clk, step;
    wire [31:0] pc,instr,rdata,rdaddr,wraddr,wdata;
    wire rden,wren;
    wire [3:0] strb;
    wire [2:0] load_type;
    wire fault,req_valid,req_ready,req_write,resp_ready;
    wire [31:0] req_addr,req_data;
    wire [3:0] req_strb;
    reg resp_valid=0,pending=0;
    reg [31:0] resp_data=0;
    reg [31:0] rom[0:1023];
    reg [31:0] expected[0:3];
    reg [31:0] target_pc,load_pc,want,operand_a,operand_b;
    reg timer_irq=0,armed=0,irq_sent=0;
    integer n,seen,reads,cycles,launches,retires,writebacks,traps;
    integer phase=0,source=0,shape=0,operation=4;
    integer case_count=0,irq_cases=0,fault_cases=0;
    integer s,o,p,c;
    reg [63:0] counter_before;
    // source: 0 IRQ; 1 instruction PF; 2 older-load PF;
    //         3 instruction PF + IRQ; 4 older-load PF + IRQ.
    // phase: 0 launch; 1 final iteration; 2 result consumption.
    wire instr_fault=armed && (source==1 || source==3) && pc==target_pc;
    wire load_fault=armed && (source==2 || source==4) &&
                    cpu.id_ex_inst0_pc_out==target_pc && rden;
    integer delay_left=0;
    riscv_cpu cpu (
        .clk(cpu_clk), .rst(rst), .module_instr_in(instr),
        .module_read_data_in(rdata), .module_pc_out(pc),
        .module_wr_data_out(wdata), .module_mem_wr_en(wren),
        .module_mem_rd_en(rden), .module_read_addr(rdaddr),
        .module_write_addr(wraddr), .module_write_byte_enable(strb),
        .module_load_type(load_type), .module_load_page_fault_in(load_fault),
        .module_store_page_fault_in(1'b0), .module_page_fault_addr_in(32'b0),
        .module_instr_page_fault_in(instr_fault),
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
        assign rdata=32'h12345678;
        assign fault=0;
        assign req_valid=0;
    end endgenerate

    function automatic [31:0] fetch(input [31:0] address);
        if(address>=32'h80000000 && address<32'h80001000)
            fetch=rom[(address-32'h80000000)>>2];
        else begin $fatal(1,"unexpected fetch %h",address); fetch=0; end
    endfunction
    function automatic [31:0] reference_div(input [31:0] a,b,input integer op);
        reg signed [63:0] sa,sb,v;
        begin
            sa={{32{a[31]}},a}; sb={{32{b[31]}},b};
            if(b==0) reference_div=op>=6?a:32'hffffffff;
            else begin
                case(op)
                    4: v=sa/sb;
                    5: v={32'b0,a}/{32'b0,b};
                    6: v=sa%sb;
                    7: v={32'b0,a}%{32'b0,b};
                endcase
                reference_div=v[31:0];
            end
        end
    endfunction
    task emit(input [31:0] ins);
        begin rom[n]=ins; n=n+1; end
    endtask
    task li(input integer rd,input [31:0] value);
        begin
            emit(((value+32'h800)&32'hfffff000)|(rd<<7)|32'h37);
            emit(((value&32'hfff)<<20)|(rd<<15)|(rd<<7)|32'h13);
        end
    endtask
    task save(input integer rd);
        emit((rd<<20)|(20<<15)|32'h2023);
    endtask
    task check_store(input [31:0] address,value,input [3:0] enables);
        begin
            if(address!==32'h10000000 || enables!==15 || seen>=4)
                $fatal(1,"unexpected/duplicate store #%0d %h",seen,address);
            if(value!==expected[seen])
                $fatal(1,"store #%0d got=%h expected=%h",seen,value,expected[seen]);
            seen=seen+1;
        end
    endtask
    assign req_ready=!pending && !resp_valid && cycles%5!=0;
    always @(posedge clk) begin
        if(rst) begin pending<=0; resp_valid<=0; cycles<=0; delay_left<=0; end
        else begin
            cycles<=cycles+1;
            if(fault) $fatal(1,"sequencer fault");
            if(cycles>20000) $fatal(1,"timeout source=%0d phase=%0d shape=%0d op=%0d pc=%h",
                                   source,phase,shape,operation,pc);
            if(GATED && req_valid && req_ready) begin
                if(req_write) begin
                    check_store(req_addr,req_data,req_strb); resp_data<=0;
                end else if(req_addr==32'h10010000) begin
                    reads=reads+1; resp_data<=32'h12345678;
                end else resp_data<=fetch(req_addr);
                pending<=1; delay_left<=1+cycles%7;
            end
            if(pending) begin
                if(delay_left==0) begin pending<=0; resp_valid<=1; end
                else delay_left<=delay_left-1;
            end
            if(resp_valid && resp_ready) resp_valid<=0;
        end
    end

    // mip samples the external timer input at a CPU edge. Assert it one
    // enabled edge before the desired trap edge, not at a wall-clock delay.
    always @(negedge cpu_clk) begin
        if(!rst && armed && !irq_sent && (source==0 || source>=3)) begin
            if((phase==0 && cpu.id_ex_inst0_instr_valid_out &&
                           cpu.id_ex_inst0_pc_out==load_pc) ||
               (phase==1 && cpu.div_busy && cpu.divider_inst.count_q==30) ||
               (phase==2 && shape==0 && cpu.div_busy && cpu.divider_inst.count_q==31) ||
               (phase==2 && shape!=0 && cpu.div_instruction &&
                            cpu.id_ex_inst0_pc_out==target_pc && !cpu.div_busy && !cpu.div_done)) begin
                timer_irq=1; irq_sent=1;
            end
        end
    end
    always @(posedge cpu_clk) begin
        if(rst) begin
            seen=0; reads=0; launches=0; retires=0; writebacks=0; traps=0;
        end else begin
            if(!GATED && wren) check_store(wraddr,wdata,strb);
            if(!GATED && rden) begin
                if(rdaddr!==32'h10010000) $fatal(1,"unexpected load");
                reads=reads+1;
            end
            if(cpu.div_start) launches=launches+1;
            if(cpu.div_instruction && cpu.instret_increment) begin
                if(traps!=1) $fatal(1,"divide retired before cancellation");
                retires=retires+1;
            end
            if(cpu.mem_wb_inst0_pc_out==target_pc && cpu.mem_wb_inst0_rd_valid_out) begin
                if(traps!=1 || cpu.wb_inst0_rd_value_out!==want)
                    $fatal(1,"stale/wrong divide WB %h expected=%h",cpu.wb_inst0_rd_value_out,want);
                writebacks=writebacks+1;
            end
            if(cpu.interrupt_taken_qualified || cpu.instr_stage_page_fault_taken ||
               cpu.mem_stage_page_fault_taken) begin
                if(!armed || traps!=0 || !cpu.div_instruction ||
                   cpu.id_ex_inst0_pc_out!==target_pc)
                    $fatal(1,"trap outside target divide");
                if(phase==0 && (cpu.div_busy || cpu.div_done || cpu.div_start))
                    $fatal(1,"launch collision not suppressed");
                if(phase==1 && (!cpu.div_busy || cpu.div_done || cpu.divider_inst.count_q!=31))
                    $fatal(1,"missed final-iteration collision");
                if(phase==2 && (cpu.div_busy || !cpu.div_done))
                    $fatal(1,"missed consume collision");
                if(!cpu.pipeline_flush || cpu.instret_increment)
                    $fatal(1,"trap did not suppress retirement/flush");
                if(source==0 && !cpu.interrupt_taken_qualified)
                    $fatal(1,"missing qualified interrupt");
                if(source!=0 && cpu.interrupt_taken_qualified)
                    $fatal(1,"interrupt beat synchronous fault");
                if(source>=3 && !cpu.interrupt_pending)
                    $fatal(1,"priority collision lacked pending interrupt");
                if((source==1 || source==3) && !cpu.instr_stage_page_fault_taken)
                    $fatal(1,"instruction fault missing");
                if((source==2 || source==4) && !cpu.mem_stage_load_page_fault)
                    $fatal(1,"older load fault missing");
                counter_before=cpu.csr_file_inst.instret_counter;
                traps=traps+1;
                // Observe committed state after all CPU NBA updates.
                #1;
                if(cpu.div_busy || cpu.div_done || cpu.id_ex_inst0_instr_valid_out ||
                   cpu.ex_mem_inst0_rd_valid_out || pc!==32'h80000f00)
                    $fatal(1,"cancel/redirect left live pipeline state");
                if(cpu.csr_file_inst.instret_counter!==counter_before)
                    $fatal(1,"trap edge incremented instret");
                if(cpu.csr_file_inst.mepc !== ((source==2 || source==4)?load_pc:target_pc))
                    $fatal(1,"wrong trap resume PC %h",cpu.csr_file_inst.mepc);
                if(cpu.csr_file_inst.mcause !== (source==0?32'h80000007:
                                                (source==1 || source==3)?32'd12:32'd13))
                    $fatal(1,"wrong trap cause %h",cpu.csr_file_inst.mcause);
                armed=0; timer_irq=0;
            end
        end
    end
    task run_case(input integer shape_in,op_in,phase_in,source_in);
        integer i;
        begin
            @(negedge clk); rst=1; armed=0; timer_irq=0; irq_sent=0;
            repeat(5) @(negedge clk);
            shape=shape_in; operation=op_in; phase=phase_in; source=source_in;
            operand_a=shape==2?32'h80000000:32'hffffff9b;
            operand_b=shape==2?32'hffffffff:shape==1?0:7;
            want=reference_div(operand_a,operand_b,operation);
            expected[0]=operand_a; expected[1]=want; expected[2]=want+1; expected[3]=32'h55;
            for(i=0;i<1024;i=i+1) rom[i]=32'h00000013;
            n=0;
            li(20,32'h10000000); li(21,32'h10010000);
            li(22,32'h80000f00); emit(32'h305b1073); // mtvec
            li(22,32'h80); emit(32'h304b1073); // mie.MTIE
            li(22,8); emit(32'h300b1073); // mstatus.MIE
            li(1,operand_a); li(2,operand_b);
            save(1); // older side effect must not repeat on divide retry
            load_pc=32'h80000000+4*n;
            emit((21<<15)|(11<<7)|32'h2003); // independent older LW
            target_pc=32'h80000000+4*n;
            emit(32'h02000033|(2<<20)|(1<<15)|(operation<<12)|(3<<7));
            save(3); // younger, dependent side effect must occur once
            emit((1<<20)|(3<<15)|(4<<7)|32'h13); save(4);
            li(5,32'h55); save(5); emit(32'h0000006f);
            rom[960]=32'h30200073; // MRET retries faulting load or divide
            armed=1; rst=0;
            wait(seen==4);
            repeat(50) @(negedge cpu_clk);
            if(traps!=1 || launches!=(phase==0?1:2) || retires!=1 || writebacks!=1 ||
               reads!=((source==2 || source==4)?2:1) ||
               cpu.rf_inst0.register_file[3]!==want ||
               cpu.rf_inst0.register_file[4]!==want+1 ||
               cpu.rf_inst0.register_file[11]!==32'h12345678)
                $fatal(1,"counts/state: traps=%0d launch=%0d retire=%0d WB=%0d reads=%0d",
                       traps,launches,retires,writebacks,reads);
            case_count=case_count+1;
            if(source==0) irq_cases=irq_cases+1; else fault_cases=fault_cases+1;
            $display("PASS collision GATED=%0d shape=%0d op=%0d phase=%0d source=%0d launches=%0d retire=%0d WB=%0d stores=%0d reads=%0d",
                     GATED,shape,operation,phase,source,launches,retires,writebacks,seen,reads);
        end
    endtask
    initial begin
        for(s=0;s<3;s=s+1) for(o=4;o<8;o=o+1) begin
            if(s!=2 || o==4 || o==6) begin
                for(p=0;p<3;p=p+1)
                    if(s==0 || p!=1) run_case(s,o,p,0);
                for(c=1;c<5;c=c+1) run_case(s,o,0,c);
            end
        end
        if(case_count!=64 || irq_cases!=24 || fault_cases!=40)
            $fatal(1,"coverage count mismatch");
        $display("PASS CPU collision matrix GATED=%0d cases=%0d irq-boundaries=%0d fault-priority=%0d stores=256",
                 GATED,case_count,irq_cases,fault_cases);
        $finish;
    end
endmodule
