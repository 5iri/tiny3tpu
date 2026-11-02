#include "Vtiny3tpu_fpu_mmio.h"
#include "tiny3tpu_program_math.h"
#include <bit>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>

static bool same_f32_or_nan(uint32_t got, uint32_t exp) {
    bool got_nan = (got & 0x7fffffffU) > 0x7f800000U;
    bool exp_nan = (exp & 0x7fffffffU) > 0x7f800000U;
    if (got_nan && exp_nan) return true;
    return got == exp;
}

int main() {
    Vtiny3tpu_fpu_mmio d;
    auto tick = [&]() {
        d.clk = 0;
        d.eval();
        d.clk = 1;
        d.eval();
    };
    auto read = [&](unsigned a) {
        d.addr = a;
        d.wr = 0;
        d.eval();
        return uint32_t(d.rdata);
    };
    auto write = [&](unsigned a, uint32_t v, unsigned strobe = 15) {
        d.addr = a;
        d.wdata = v;
        d.wstrb = strobe;
        d.wr = 1;
        tick();
        d.wr = 0;
        d.eval();
    };

    d.wr = 0;
    d.rst = 1;
    tick();
    d.rst = 0;
    tick();

    if (read(0x3c) != 0x46505531U || read(0x00) != 0U || read(0x04) != 0U) return 1;
    write(0x00, 0x12345678U);
    write(0x00, 0xdeadbeefU, 0x3); // partial write must be ignored
    if (read(0x00) != 0x12345678U) return 2;

    std::mt19937 rng(0x73707531U);
    std::vector<uint32_t> ints = {
        0U, 1U, 2U, 3U, 0xffffffffU, 0x80000000U, 0x7fffffffU,
        0x00ffffffU, 0x01000000U, 0x01000001U, 0x01000002U, 0x01000003U,
        0x7fffff7fU, 0x7fffff80U, 0x7fffff81U, 0x7fffffc0U, 0x80000080U
    };
    for (int i = 0; i < 50000; ++i) ints.push_back(rng());

    for (uint32_t u : ints) {
        write(0x00, u);
        int32_t s = static_cast<int32_t>(u);
        uint32_t exp_i2f = std::bit_cast<uint32_t>(static_cast<float>(s));
        uint32_t exp_u2f = std::bit_cast<uint32_t>(static_cast<float>(u));
        if (read(0x14) != exp_i2f) {
            std::cerr << "I2F mismatch for " << s << ": got " << std::hex << read(0x14) << " expected " << exp_i2f << "\n";
            return 3;
        }
        if (read(0x18) != exp_u2f) {
            std::cerr << "U2F mismatch for " << u << ": got " << std::hex << read(0x18) << " expected " << exp_u2f << "\n";
            return 4;
        }
    }

    std::vector<uint32_t> floats = {
        0x00000000U, 0x80000000U, 0x3f800000U, 0xbf800000U,
        0x3f000000U, 0xbf000000U, 0x7f800000U, 0xff800000U,
        0x7fc00000U, 0xffc00001U, 0x00000001U, 0x80000001U,
        0x007fffffU, 0x807fffffU, 0x00800000U, 0x80800000U,
        0x7f7fffffU, 0xff7fffffU, 0x42fe0000U, 0xc3000000U,
        0x437f0000U, 0x4f000000U, 0xcf000000U, 0x4f800000U
    };
    for (int i = 0; i < 2000; ++i) floats.push_back(rng());

    for (uint32_t ua : floats) {
        float fa = std::bit_cast<float>(ua);
        write(0x00, ua);
        if (read(0x1c) != static_cast<uint32_t>(t3p_to_int32(fa))) return 5;
        if (read(0x20) != t3p_to_uint32(fa)) return 6;
        if (read(0x24) != static_cast<uint32_t>(static_cast<int32_t>(t3p_to_int8(fa)))) return 7;
        if (read(0x28) != static_cast<uint32_t>(t3p_to_uint8(fa))) return 8;
    }

    for (size_t i = 0; i < 400; ++i) {
        uint32_t ua = floats[i];
        float fa = std::bit_cast<float>(ua);
        write(0x00, ua);
        for (size_t j = 0; j < 400; ++j) {
            uint32_t ub = floats[j];
            float fb = std::bit_cast<float>(ub);
            write(0x04, ub);

            uint32_t exp_add = std::bit_cast<uint32_t>(fa + fb);
            uint32_t exp_sub = std::bit_cast<uint32_t>(fa - fb);
            uint32_t exp_mul = std::bit_cast<uint32_t>(fa * fb);
            uint32_t exp_min = std::bit_cast<uint32_t>(t3p_min(fa, fb));
            uint32_t exp_max = std::bit_cast<uint32_t>(t3p_max(fa, fb));
            uint32_t exp_bias = std::bit_cast<uint32_t>(static_cast<float>(t3p_i32(ua + ub)));

            if (!same_f32_or_nan(read(0x08), exp_add)) {
                std::cerr << "FADD mismatch ua=" << std::hex << ua << " ub=" << ub
                          << " got=" << read(0x08) << " exp=" << exp_add << "\n";
                return 9;
            }
            if (!same_f32_or_nan(read(0x0c), exp_sub)) {
                std::cerr << "FSUB mismatch ua=" << std::hex << ua << " ub=" << ub
                          << " got=" << read(0x0c) << " exp=" << exp_sub << "\n";
                return 10;
            }
            if (!same_f32_or_nan(read(0x10), exp_mul)) {
                std::cerr << "FMUL mismatch ua=" << std::hex << ua << " ub=" << ub
                          << " got=" << read(0x10) << " exp=" << exp_mul << "\n";
                return 11;
            }
            if (read(0x30) != exp_min) return 12;
            if (read(0x34) != exp_max) return 13;
            if (read(0x2c) != exp_bias) return 14;
        }
    }

    std::cout << "PASS FPU MMIO: identity, partial writes, I2F, U2F, F2I, F2U, F2I8, F2U8, FADD, FSUB, FMUL, FMIN, FMAX, I2F_BIAS\n";
    return 0;
}
