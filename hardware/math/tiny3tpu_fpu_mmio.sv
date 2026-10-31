`timescale 1ns/1ps
`default_nettype none
`ifndef TINY3TPU_FPU_MMIO_SV
`define TINY3TPU_FPU_MMIO_SV
// Single-cycle IEEE-754 binary32 MMIO FPU & Quantization Co-Processor.
// Base offset in VexRiscv SoC: 0x20003040 (64-byte aperture: offsets 0x00..0x3C).
// Word registers:
//   0x00 (OPA):       Operand A (binary32 or int32/uint32)
//   0x04 (OPB):       Operand B (binary32 or int32/uint32)
//   0x08 (FADD):      Read IEEE-754 float32(OPA) + float32(OPB) (RNE)
//   0x0C (FSUB):      Read IEEE-754 float32(OPA) - float32(OPB) (RNE)
//   0x10 (FMUL):      Read IEEE-754 float32(OPA) * float32(OPB) (RNE)
//   0x14 (I2F):       Read IEEE-754 float32(int32(OPA)) (RNE)
//   0x18 (U2F):       Read IEEE-754 float32(uint32(OPA)) (RNE)
//   0x1C (F2I):       Read saturating int32(float32(OPA)) (trunc, NaN->0)
//   0x20 (F2U):       Read saturating uint32(float32(OPA)) (trunc, NaN/neg->0)
//   0x24 (F2I8):      Read saturating int8(float32(OPA)) sign-extended to int32
//   0x28 (F2U8):      Read saturating uint8(float32(OPA)) zero-extended to uint32
//   0x2C (I2F_BIAS):  Read IEEE-754 float32(int32(OPA + OPB)) (RNE)
//   0x30 (FMIN):      Read t3p_min(float32(OPA), float32(OPB))
//   0x34 (FMAX):      Read t3p_max(float32(OPA), float32(OPB))
//   0x3C (ID):        Read identity 0x46505531 ("FPU1")
module tiny3tpu_fpu_mmio(
    input wire clk,
    input wire rst,
    input wire wr,
    input wire [5:0] addr,
    input wire [31:0] wdata,
    input wire [3:0] wstrb,
    output reg [31:0] rdata
);
    reg [31:0] opa, opb;

    always @(posedge clk) begin
        if (rst) begin
            opa <= 32'd0;
            opb <= 32'd0;
        end else if (wr && wstrb == 4'hf) begin
            if (addr == 6'h00) opa <= wdata;
            else if (addr == 6'h04) opb <= wdata;
        end
    end

    function automatic [5:0] clz32(input [31:0] v);
        integer k;
        reg found;
        begin
            clz32 = 6'd32;
            found = 1'b0;
            for (k = 31; k >= 0; k = k - 1) begin
                if (!found && v[k]) begin
                    clz32 = 6'd31 - k[5:0];
                    found = 1'b1;
                end
            end
        end
    endfunction

    function automatic [4:0] clz24(input [23:0] v);
        integer k;
        reg found;
        begin
            clz24 = 5'd24;
            found = 1'b0;
            for (k = 23; k >= 0; k = k - 1) begin
                if (!found && v[k]) begin
                    clz24 = 5'd23 - k[4:0];
                    found = 1'b1;
                end
            end
        end
    endfunction

    function automatic [4:0] clz27(input [26:0] v);
        integer k;
        reg found;
        begin
            clz27 = 5'd27;
            found = 1'b0;
            for (k = 26; k >= 0; k = k - 1) begin
                if (!found && v[k]) begin
                    clz27 = 5'd26 - k[4:0];
                    found = 1'b1;
                end
            end
        end
    endfunction

    function automatic [31:0] int_to_f32(input [31:0] x, input is_signed);
        reg sign;
        reg [31:0] mag;
        reg [5:0] lz;
        reg [31:0] norm;
        reg [7:0] exp;
        reg [22:0] mant;
        reg round_bit, sticky_bit, inc;
        reg [23:0] rounded;
        begin
            if (x == 32'd0) begin
                int_to_f32 = 32'd0;
            end else begin
                sign = is_signed && x[31];
                mag = sign ? (32'd0 - x) : x;
                lz = clz32(mag);
                norm = mag << lz;
                exp = 8'd158 - {2'b00, lz};
                mant = norm[30:8];
                round_bit = norm[7];
                sticky_bit = |norm[6:0];
                inc = round_bit & (sticky_bit | mant[0]);
                rounded = {1'b0, mant} + {23'd0, inc};
                int_to_f32 = {sign, exp + {7'd0, rounded[23]}, rounded[22:0]};
            end
        end
    endfunction

    function automatic [31:0] f32_to_i32(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [7:0] exp;
        reg [31:0] mag;
        begin
            sign = x[31];
            ax = x[30:0];
            if (ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_i32 = 32'd0;
            end else if (ax >= 31'h4f000000) begin
                f32_to_i32 = sign ? 32'h80000000 : 32'h7fffffff;
            end else begin
                exp = ax[30:23] - 8'd127;
                mag = {8'd0, 1'b1, ax[22:0]};
                if (exp >= 8'd23) mag = mag << (exp - 8'd23);
                else mag = mag >> (8'd23 - exp);
                f32_to_i32 = sign ? (32'd0 - mag) : mag;
            end
        end
    endfunction

    function automatic [31:0] f32_to_u32(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [7:0] exp;
        reg [31:0] mag;
        begin
            sign = x[31];
            ax = x[30:0];
            if (sign || ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_u32 = 32'd0;
            end else if (ax >= 31'h4f800000) begin
                f32_to_u32 = 32'hffffffff;
            end else begin
                exp = ax[30:23] - 8'd127;
                mag = {8'd0, 1'b1, ax[22:0]};
                if (exp >= 8'd23) mag = mag << (exp - 8'd23);
                else mag = mag >> (8'd23 - exp);
                f32_to_u32 = mag;
            end
        end
    endfunction

    function automatic [31:0] f32_to_i8(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [31:0] mag;
        reg [31:0] signed_val;
        begin
            sign = x[31];
            ax = x[30:0];
            if (ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_i8 = 32'd0;
            end else if (!sign && ax >= 31'h42fe0000) begin
                f32_to_i8 = 32'd127;
            end else if (sign && ax >= 31'h43000000) begin
                f32_to_i8 = 32'hffffff80;
            end else begin
                mag = ({8'd0, 1'b1, ax[22:0]}) >> (8'd150 - ax[30:23]);
                signed_val = sign ? (32'd0 - mag) : mag;
                f32_to_i8 = {{24{signed_val[7]}}, signed_val[7:0]};
            end
        end
    endfunction

    function automatic [31:0] f32_to_u8(input [31:0] x);
        reg sign;
        reg [30:0] ax;
        reg [31:0] mag;
        begin
            sign = x[31];
            ax = x[30:0];
            if (sign || ax < 31'h3f800000 || ax > 31'h7f800000) begin
                f32_to_u8 = 32'd0;
            end else if (ax >= 31'h437f0000) begin
                f32_to_u8 = 32'd255;
            end else begin
                mag = ({8'd0, 1'b1, ax[22:0]}) >> (8'd150 - ax[30:23]);
                f32_to_u8 = {24'd0, mag[7:0]};
            end
        end
    endfunction

    function automatic [31:0] f32_add(input [31:0] a, input [31:0] b);
        reg sa, sb, s_big, s_small;
        reg [7:0] ea, eb, e_big, e_small;
        reg [22:0] fa, fb, f_big, f_small;
        reg a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        reg swap;
        reg [8:0] exp_big, exp_small, diff, exp_norm, max_shift;
        reg [26:0] sig_big, sig_small_raw, sig_small, norm;
        reg [53:0] wide_shift;
        reg [27:0] sum;
        reg [26:0] diff_sig;
        reg [4:0] lzc;
        reg [22:0] mant;
        reg g, r, s, inc;
        reg [23:0] rounded;
        reg [8:0] final_exp;
        begin
            sa = a[31]; ea = a[30:23]; fa = a[22:0];
            sb = b[31]; eb = b[30:23]; fb = b[22:0];
            a_nan = (ea == 8'hff) && (fa != 23'd0);
            b_nan = (eb == 8'hff) && (fb != 23'd0);
            a_inf = (ea == 8'hff) && (fa == 23'd0);
            b_inf = (eb == 8'hff) && (fb == 23'd0);
            a_zero = (ea == 8'd0) && (fa == 23'd0);
            b_zero = (eb == 8'd0) && (fb == 23'd0);

            if (a_nan || b_nan) begin
                f32_add = 32'h7fc00000;
            end else if (a_inf && b_inf) begin
                f32_add = (sa != sb) ? 32'h7fc00000 : {sa, 8'hff, 23'd0};
            end else if (a_inf) begin
                f32_add = {sa, 8'hff, 23'd0};
            end else if (b_inf) begin
                f32_add = {sb, 8'hff, 23'd0};
            end else if (a_zero && b_zero) begin
                f32_add = {sa & sb, 31'd0};
            end else if (a_zero) begin
                f32_add = b;
            end else if (b_zero) begin
                f32_add = a;
            end else begin
                swap = ({eb, fb} > {ea, fa});
                s_big = swap ? sb : sa;
                e_big = swap ? eb : ea;
                f_big = swap ? fb : fa;
                s_small = swap ? sa : sb;
                e_small = swap ? ea : eb;
                f_small = swap ? fa : fb;

                exp_big = (e_big == 8'd0) ? 9'd1 : {1'b0, e_big};
                exp_small = (e_small == 8'd0) ? 9'd1 : {1'b0, e_small};
                diff = exp_big - exp_small;

                sig_big = {e_big != 8'd0, f_big, 3'b000};
                sig_small_raw = {e_small != 8'd0, f_small, 3'b000};

                if (diff == 9'd0) begin
                    sig_small = sig_small_raw;
                end else if (diff >= 9'd27) begin
                    sig_small = {26'd0, |sig_small_raw};
                end else begin
                    wide_shift = {sig_small_raw, 27'd0} >> diff;
                    sig_small = {wide_shift[53:28], wide_shift[27] | (|wide_shift[26:0])};
                end

                if (s_big == s_small) begin
                    sum = {1'b0, sig_big} + {1'b0, sig_small};
                    if (sum[27]) begin
                        norm = {sum[27:2], sum[1] | sum[0]};
                        exp_norm = exp_big + 9'd1;
                    end else if (sum[26]) begin
                        norm = sum[26:0];
                        exp_norm = exp_big;
                    end else begin
                        norm = sum[26:0];
                        exp_norm = 9'd0;
                    end
                    mant = norm[25:3];
                    g = norm[2]; r = norm[1]; s = norm[0];
                    inc = g & (r | s | mant[0]);
                    rounded = {1'b0, mant} + {23'd0, inc};
                    if (exp_norm == 9'd0) begin
                        final_exp = (rounded[23] || norm[26]) ? 9'd1 : 9'd0;
                    end else begin
                        final_exp = exp_norm + {8'd0, rounded[23]};
                    end
                    if (final_exp >= 9'd255) f32_add = {s_big, 8'hff, 23'd0};
                    else f32_add = {s_big, final_exp[7:0], rounded[22:0]};
                end else begin
                    diff_sig = sig_big - sig_small;
                    if (diff_sig == 27'd0) begin
                        f32_add = 32'd0;
                    end else begin
                        lzc = clz27(diff_sig);
                        max_shift = exp_big - 9'd1;
                        if ({4'd0, lzc} <= max_shift) begin
                            norm = diff_sig << lzc;
                            exp_norm = exp_big - {4'd0, lzc};
                        end else begin
                            norm = diff_sig << max_shift[4:0];
                            exp_norm = 9'd0;
                        end
                        if (!norm[26]) exp_norm = 9'd0;
                        mant = norm[25:3];
                        g = norm[2]; r = norm[1]; s = norm[0];
                        inc = g & (r | s | mant[0]);
                        rounded = {1'b0, mant} + {23'd0, inc};
                        if (exp_norm == 9'd0) begin
                            final_exp = rounded[23] ? 9'd1 : 9'd0;
                        end else begin
                            final_exp = exp_norm + {8'd0, rounded[23]};
                        end
                        f32_add = {s_big, final_exp[7:0], rounded[22:0]};
                    end
                end
            end
        end
    endfunction

    function automatic [31:0] f32_mul(input [31:0] a, input [31:0] b);
        reg sa, sb, sign;
        reg [7:0] ea, eb;
        reg [22:0] fa, fb;
        reg a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        reg [4:0] lza, lzb;
        reg [23:0] sig_a, sig_b;
        reg signed [10:0] exp_a, exp_b, exp_sum, rshift, exp_out;
        reg [47:0] prod, norm_prod;
        reg [25:0] sub_in;
        reg [51:0] sub_shift;
        reg [24:0] sub_sig;
        reg round_bit, sticky_bit, inc;
        reg [23:0] rounded;
        begin
            sa = a[31]; ea = a[30:23]; fa = a[22:0];
            sb = b[31]; eb = b[30:23]; fb = b[22:0];
            sign = sa ^ sb;
            a_nan = (ea == 8'hff) && (fa != 23'd0);
            b_nan = (eb == 8'hff) && (fb != 23'd0);
            a_inf = (ea == 8'hff) && (fa == 23'd0);
            b_inf = (eb == 8'hff) && (fb == 23'd0);
            a_zero = (ea == 8'd0) && (fa == 23'd0);
            b_zero = (eb == 8'd0) && (fb == 23'd0);

            if (a_nan || b_nan || (a_inf && b_zero) || (b_inf && a_zero)) begin
                f32_mul = 32'h7fc00000;
            end else if (a_inf || b_inf) begin
                f32_mul = {sign, 8'hff, 23'd0};
            end else if (a_zero || b_zero) begin
                f32_mul = {sign, 31'd0};
            end else begin
                if (ea == 8'd0) begin
                    lza = clz24({1'b0, fa});
                    sig_a = {1'b0, fa} << lza;
                    exp_a = 11'sd1 - $signed({6'd0, lza});
                end else begin
                    sig_a = {1'b1, fa};
                    exp_a = $signed({3'd0, ea});
                end
                if (eb == 8'd0) begin
                    lzb = clz24({1'b0, fb});
                    sig_b = {1'b0, fb} << lzb;
                    exp_b = 11'sd1 - $signed({6'd0, lzb});
                end else begin
                    sig_b = {1'b1, fb};
                    exp_b = $signed({3'd0, eb});
                end

                prod = sig_a * sig_b;
                exp_sum = exp_a + exp_b - 11'sd127 + (prod[47] ? 11'sd1 : 11'sd0);
                norm_prod = prod[47] ? prod : (prod << 1);

                if (exp_sum >= 11'sd255) begin
                    f32_mul = {sign, 8'hff, 23'd0};
                end else if (exp_sum <= 11'sd0) begin
                    rshift = 11'sd1 - exp_sum;
                    if (rshift > 11'sd25) begin
                        f32_mul = {sign, 31'd0};
                    end else begin
                        sub_in = {norm_prod[47:23], |norm_prod[22:0]};
                        sub_shift = {sub_in, 26'd0} >> rshift[4:0];
                        sub_sig = {sub_shift[50:27], |sub_shift[26:0]};
                        round_bit = sub_sig[1];
                        sticky_bit = sub_sig[0];
                        inc = round_bit & (sticky_bit | sub_sig[2]);
                        rounded = {1'b0, sub_sig[24:2]} + {23'd0, inc};
                        f32_mul = {sign, rounded[23] ? 8'd1 : 8'd0, rounded[22:0]};
                    end
                end else begin
                    round_bit = norm_prod[23];
                    sticky_bit = |norm_prod[22:0];
                    inc = round_bit & (sticky_bit | norm_prod[24]);
                    rounded = {1'b0, norm_prod[46:24]} + {23'd0, inc};
                    exp_out = exp_sum + (rounded[23] ? 11'sd1 : 11'sd0);
                    if (exp_out >= 11'sd255) f32_mul = {sign, 8'hff, 23'd0};
                    else f32_mul = {sign, exp_out[7:0], rounded[22:0]};
                end
            end
        end
    endfunction

    function automatic [31:0] f32_min_max(input [31:0] a, input [31:0] b, input is_max);
        reg signed [31:0] ka, kb;
        begin
            if (a[30:0] > 31'h7f800000) f32_min_max = a;
            else if (b[30:0] > 31'h7f800000) f32_min_max = b;
            else begin
                ka = $signed(a ^ ({32{a[31]}} & 32'h7fffffff));
                kb = $signed(b ^ ({32{b[31]}} & 32'h7fffffff));
                if (is_max) f32_min_max = (ka > kb) ? a : b;
                else f32_min_max = (ka < kb) ? a : b;
            end
        end
    endfunction

    always @* begin
        case (addr)
            6'h00: rdata = opa;
            6'h04: rdata = opb;
            6'h08: rdata = f32_add(opa, opb);
            6'h0c: rdata = (opb[30:0] > 31'h7f800000) ? 32'h7fc00000 : f32_add(opa, {~opb[31], opb[30:0]});
            6'h10: rdata = f32_mul(opa, opb);
            6'h14: rdata = int_to_f32(opa, 1'b1);
            6'h18: rdata = int_to_f32(opa, 1'b0);
            6'h1c: rdata = f32_to_i32(opa);
            6'h20: rdata = f32_to_u32(opa);
            6'h24: rdata = f32_to_i8(opa);
            6'h28: rdata = f32_to_u8(opa);
            6'h2c: rdata = int_to_f32(opa + opb, 1'b1);
            6'h30: rdata = f32_min_max(opa, opb, 1'b0);
            6'h34: rdata = f32_min_max(opa, opb, 1'b1);
            6'h3c: rdata = 32'h46505531;
            default: rdata = 32'd0;
        endcase
    end
endmodule
`endif
`default_nettype wire
