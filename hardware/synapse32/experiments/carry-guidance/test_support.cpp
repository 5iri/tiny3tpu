#include "carry_support.h"
#include <cassert>
#include <cstdio>
#include <vector>

// Independent truth-table oracle: evaluate the four CARRY4 mux/XOR stages,
// then flip each dynamic input to discover exact Boolean support.
int main()
{
    for (unsigned configuration = 0; configuration < 19683; ++configuration) {
        unsigned code = configuration;
        std::array<int, 9> values;
        std::vector<unsigned> variables;
        for (unsigned i = 0; i < 9; ++i) {
            values[i] = int(code % 3) - 1;
            code /= 3;
            if (values[i] < 0)
                variables.push_back(i);
        }
        std::vector<unsigned> truth(1u << variables.size());
        for (unsigned row = 0; row < truth.size(); ++row) {
            auto pins = values;
            for (unsigned j = 0; j < variables.size(); ++j)
                pins[variables[j]] = (row >> j) & 1u;
            unsigned carry = pins[8], outputs = 0;
            for (unsigned i = 0; i < 4; ++i) {
                outputs |= (pins[i] ^ carry) << (2 * i);
                carry = pins[i] ? carry : pins[i + 4];
                outputs |= carry << (2 * i + 1);
            }
            truth[row] = outputs;
        }
        std::array<unsigned, 8> expected{};
        for (unsigned j = 0; j < variables.size(); ++j) {
            unsigned changed = 0;
            for (unsigned row = 0; row < truth.size(); ++row)
                changed |= truth[row] ^ truth[row ^ (1u << j)];
            for (unsigned output = 0; output < 8; ++output)
                if (changed & (1u << output))
                    expected[output] |= 1u << variables[j];
        }
        assert(tiny3tpu::carry_support(values) == expected);
    }
    std::puts("PASS all 19683 constant/dynamic CARRY4 input configurations");
}
