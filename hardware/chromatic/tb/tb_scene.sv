`timescale 1ns/1ps
module tb_scene;
    reg clk=0;always #5 clk=~clk;
    reg reset=1,tick=0,done=0;
    reg [7:0] held=0,pressed=0;
    wire start,bank,valid,paused,reverse;
    wire [7:0] phase,display_phase;
    wire [2:0] speed;wire [31:0] cycles;wire [15:0] frames;
    scene dut(clk,reset,tick,done,held,pressed,start,bank,valid,phase,display_phase,paused,reverse,speed,cycles,frames);
    task step;begin @(posedge clk);#1;@(negedge clk);end endtask
    task press(input [7:0] value);begin pressed=value;step();pressed=0;step();end endtask
    task finish_frame;begin
        while(!start)step();
        step();repeat(5)step();done=1;step();done=0;step();
        tick=1;step();tick=0;step();
    end endtask
    initial begin
        step();reset=0;step();
        if(!start || valid || bank)$fatal(1,"Initial job/publication wrong");
        tick=1;step();tick=0;step();
        if(valid || bank)$fatal(1,"Published incomplete render");
        done=1;step();done=0;repeat(4)step();
        if(valid || bank || start)$fatal(1,"Published outside vblank / restarted early");
        tick=1;step();tick=0;
        if(!valid || !bank || display_phase!=0 || phase!=1 || frames!=1)$fatal(1,"First publish wrong");
        press(1);if(!paused)$fatal(1,"Pause failed");
        // START was already accepted while processing the pause input.
        done=1;step();done=0;step();tick=1;step();tick=0;
        if(phase!=1 || display_phase!=1 || bank)$fatal(1,"Paused frame not stable");
        held=32;finish_frame();if(phase!=2)$fatal(1,"Manual right failed");
        held=16;finish_frame();if(phase!=1)$fatal(1,"Manual left failed");
        held=48;finish_frame();if(phase!=1)$fatal(1,"Opposing directions moved");
        held=0;press(4);press(4);press(4);press(4);
        if(speed!=4)$fatal(1,"Speed upper bound");
        press(8);press(8);press(8);press(8);if(speed!=1)$fatal(1,"Speed lower bound");
        press(2);press(1);if(!reverse || paused)$fatal(1,"Reverse/unpause");
        done=1;step();done=0;step();tick=1;step();tick=0;
        if(phase!=0)$fatal(1,"Reverse advance failed");
        finish_frame();if(phase!=255)$fatal(1,"Phase wrap failed");
        press(64);done=1;step();done=0;step();tick=1;step();tick=0;
        if(phase!=0)$fatal(1,"Home failed");
        reset=1;step();if(valid || bank || phase || paused || reverse)$fatal(1,"Reset failed");
        $display("SCENE PASS: complete-frame vblank swaps, no early restart, pause, manual rotation, speed bounds, reverse/wrap, home/reset");
        $finish;
    end
    initial begin #100000;$fatal(1,"Scene timeout");end
endmodule
