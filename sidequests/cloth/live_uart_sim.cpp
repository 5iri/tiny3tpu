#include "Vvexriscv_tpu_soc.h"
#include "banana_fixture.h"
#include "banana_vertices.h"
#include <cstdint>
#include <iostream>
#include <vector>

static void append_word(std::vector<uint8_t>& bytes, uint32_t word) {
    for (unsigned i = 0; i < 4; ++i) bytes.push_back(uint8_t(word >> (8 * i)));
}
static uint32_t word(const std::vector<uint8_t>& bytes, size_t offset) {
    uint32_t result = 0;
    for (unsigned i = 0; i < 4; ++i) result |= uint32_t(bytes[offset + i]) << (8 * i);
    return result;
}
int main() {
    Vvexriscv_tpu_soc dut;
    dut.ext_req_ready = 1; dut.ext_resp_valid = 0;
    dut.ext_resp_rdata = 0; dut.ext_resp_error = 1;
    std::vector<uint8_t> request{'C','L','Q','2'}, received;
    append_word(request, 123);
    append_word(request, 256 | 2);
    const unsigned baud_cycles = 109;
    unsigned send_start = 4000000, frames = 0;
    int rx_bit = -1;
    unsigned rx_byte = 0, sample = 0;
    size_t response = size_t(-1);
    for (unsigned cycle = 0; cycle < 300000000; ++cycle) {
        dut.clk = 0; dut.rst = cycle < 8; dut.ready_to_run = cycle > 20;
        dut.uart_rx = 1;
        if (cycle >= send_start) {
            const unsigned bit = (cycle - send_start) / baud_cycles;
            const unsigned index = bit / 10, within = bit % 10;
            if (index < request.size())
                dut.uart_rx = within == 0 ? 0 : within == 9 ? 1 : ((request[index] >> (within - 1)) & 1);
        }
        dut.eval(); dut.clk = 1; dut.eval();
        if (dut.fault || dut.ext_req_valid || dut.exit_valid) {
            std::cerr << "Unexpected fault, exit or external-memory access\n";
            return 1;
        }
        if (rx_bit < 0 && !dut.uart_tx) {
            rx_bit = 0; rx_byte = 0; sample = cycle + baud_cycles + baud_cycles / 2;
        } else if (rx_bit >= 0 && cycle >= sample) {
            if (rx_bit < 8) {
                rx_byte |= unsigned(dut.uart_tx) << rx_bit++;
                sample += baud_cycles;
            } else {
                if (!dut.uart_tx) { std::cerr << "UART framing error cycle=" << cycle << '\n'; return 2; }
                received.push_back(uint8_t(rx_byte));
                rx_bit = -1;
                if (response == size_t(-1) && received.size() >= 4 &&
                    word(received, received.size() - 4) == 0x32524c43U) response = received.size() - 4;
            }
        }
        if (response != size_t(-1) && received.size() >= response + 32 + BANANA_VERTICES * 12) {
            if (word(received, response + 4) != 123 + frames || word(received, response + 8) ||
                word(received, response + 16) != BANANA_VERTICES || !word(received, response + 12)) {
                std::cerr << "Bad response seq=" << word(received, response + 4)
                          << " status=" << word(received, response + 8)
                          << " cycles=" << word(received, response + 12)
                          << " count=" << word(received, response + 16) << '\n'; return 3;
            }
            if (word(received,response+28)!=(frames+1)*2 || !word(received,response+24)) return 7;
            uint32_t checksum = 0;
            for (unsigned row = 0; row < BANANA_VERTICES; ++row)
                for (unsigned col = 0; col < 3; ++col) {
                    int32_t expected = banana_bias[col];
                    for (unsigned k = 0; k < 3; ++k)
                        expected += frame_vertices[frames][row * 3 + k] * banana_weights[k * 3 + col];
                    uint32_t actual = word(received, response + 32 + (row * 3 + col) * 4);
                    if (actual != uint32_t(expected)) {
                        std::cerr << "Mismatch vertex=" << row << " column=" << col << '\n';
                        return 4;
                    }
                    checksum ^= actual;
                }
            if (checksum != word(received, response + 20)) return 5;
            std::cout << "PASS live UART CPU/TPU: vertices=" << BANANA_VERTICES
                      << " compute_cycles=" << word(received, response + 12)
                      << " complete_cycle=" << cycle << " external_memory_accesses=0" << std::endl;
            if (++frames == 3) return 0;
            received.clear(); response = size_t(-1);
            request[4] = uint8_t(123 + frames);
            request[8] = 2; request[9] = 0;
            // Start another request immediately after the final stop bit.
            send_start = cycle + 2 * baud_cycles;
        }
    }
    std::cerr << "TIMEOUT at PC " << std::hex << dut.pc_debug << std::dec
              << " received_bytes=" << received.size() << '\n';
    return 6;
}
