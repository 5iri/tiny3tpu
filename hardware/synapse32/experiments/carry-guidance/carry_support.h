#pragma once
#include <array>

namespace tiny3tpu {
// Values are 0, 1, or -1 (an independent dynamic input). Input positions are
// S0..S3, DI0..DI3, selected initial carry. Outputs are O0,CO0,...,O3,CO3.
struct CarrySignal {
    int value;
    unsigned dependencies;
};
inline std::array<unsigned, 8> carry_support(const std::array<int, 9> &values)
{
    std::array<CarrySignal, 9> inputs;
    for (unsigned i = 0; i < 9; ++i)
        inputs[i] = {values[i], values[i] < 0 ? 1u << i : 0u};
    CarrySignal carry = inputs[8];
    std::array<unsigned, 8> result;
    for (unsigned i = 0; i < 4; ++i) {
        const auto s = inputs[i], d = inputs[i + 4];
        // Current S is independent of the preceding carry expression.
        result[2 * i] = s.dependencies | carry.dependencies;
        if (s.value == 0)
            carry = d;
        else if (s.value != 1) {
            if (!(carry.value >= 0 && carry.value == d.value))
                carry = {-1, s.dependencies | carry.dependencies | d.dependencies};
        }
        result[2 * i + 1] = carry.dependencies;
    }
    return result;
}
} // namespace tiny3tpu
