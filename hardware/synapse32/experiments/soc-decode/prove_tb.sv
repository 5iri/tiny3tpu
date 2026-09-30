`timescale 1ns/1ps
// Exhaustive boot-decode equivalence: original subtract range check vs the
// prefix comparison, for the production BOOT_WORDS=16384 geometry.
// The result provably depends only on req_addr[31:16]: the base and bound are
// 64 KiB-aligned, so no borrow reaches the high half in-range and any
// out-of-range address either wraps (unsigned compare false) or exceeds the
// bound (false). The sweep covers every high half with boundary low halves.
module soc_decode_prove_tb;
    reg [31:0] addr;
    wire old_hit, new_hit;
    // Exact copies of the RTL expressions (production vs overlay).
    assign old_hit = addr >= 32'h80000000 && (addr - 32'h80000000) < (16384 * 4);
    assign new_hit = addr[31:16] == 16'h8000;
    integer hi, li, checked = 0;
    reg [15:0] lows [0:5];
    initial begin
        lows[0] = 16'h0000; lows[1] = 16'h0001; lows[2] = 16'h7fff;
        lows[3] = 16'h8000; lows[4] = 16'hfffe; lows[5] = 16'hffff;
        for (hi = 0; hi < 65536; hi = hi + 1) begin
            for (li = 0; li < 6; li = li + 1) begin
                addr = {hi[15:0], lows[li]};
                #1;
                if (old_hit !== new_hit)
                    $fatal(1, "DECODE MISMATCH addr=%h old=%b new=%b", addr, old_hit, new_hit);
                checked = checked + 1;
            end
        end
        // Directed full-address corners, including wrap boundaries.
        addr = 32'h7fffffff; #1; if (old_hit !== new_hit) $fatal(1, "corner 7fffffff");
        addr = 32'h80000000; #1; if (old_hit !== new_hit) $fatal(1, "corner 80000000");
        addr = 32'h8000ffff; #1; if (old_hit !== new_hit) $fatal(1, "corner 8000ffff");
        addr = 32'h80010000; #1; if (old_hit !== new_hit) $fatal(1, "corner 80010000");
        addr = 32'hffffffff; #1; if (old_hit !== new_hit) $fatal(1, "corner ffffffff");
        addr = 32'h00000000; #1; if (old_hit !== new_hit) $fatal(1, "corner 0");
        checked = checked + 6;
        $display("PASS boot prefix decode: %0d equivalence checks", checked);
        $finish;
    end
endmodule
