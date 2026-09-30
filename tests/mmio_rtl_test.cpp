#ifndef TINY3TPU_AXIS_MAILBOX_SIM
#include "Vtiny3tpu_axi.h"
#endif
#include "tiny3tpu_mmio_backend.h"
#include <cstdint>
#include <iostream>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#ifdef TINY3TPU_AXIS_MAILBOX_SIM
#include "axis_mailbox_sim.hpp"
#else
struct Simulation {
    Vtiny3tpu_axi dut;
    bool delayed_poll = false;
    unsigned launches = 0;
    void tick() {
        dut.s_axi_aclk = 0; dut.eval();
        dut.s_axi_aclk = 1; dut.eval();
        dut.s_axi_aclk = 0; dut.eval();
    }
    Simulation() {
        dut.s_axi_aresetn = 0;
        dut.s_axi_awvalid = dut.s_axi_wvalid = dut.s_axi_arvalid = 0;
        dut.s_axi_bready = dut.s_axi_rready = 1;
        dut.s_axi_awprot = dut.s_axi_arprot = 0;
        tick(); tick(); dut.s_axi_aresetn = 1; tick();
    }
};

static int write32(void *user, uint32_t offset, uint32_t value) {
    auto& s = *static_cast<Simulation*>(user);
    auto& d = s.dut;
    d.s_axi_awaddr = offset; d.s_axi_wdata = value; d.s_axi_wstrb = 15;
    d.s_axi_awvalid = d.s_axi_wvalid = 1;
    for (unsigned cycle = 0; cycle < 100; ++cycle) {
        d.eval();
        const bool aw = d.s_axi_awvalid && d.s_axi_awready;
        const bool w = d.s_axi_wvalid && d.s_axi_wready;
        const bool response = d.s_axi_bvalid;
        const unsigned status = d.s_axi_bresp;
        s.tick();
        if (aw) d.s_axi_awvalid = 0;
        if (w) d.s_axi_wvalid = 0;
        if (response) {
            if (status == 0 && offset == 0 && value == 1) ++s.launches;
            if (offset == 0 && value == 1 && s.delayed_poll)
                for (unsigned i = 0; i < 500; ++i) s.tick();
            return status ? -1 : 0;
        }
    }
    return -1;
}

static int read32(void *user, uint32_t offset, uint32_t *value) {
    auto& s = *static_cast<Simulation*>(user);
    auto& d = s.dut;
    d.s_axi_araddr = offset; d.s_axi_arvalid = 1;
    for (unsigned cycle = 0; cycle < 100; ++cycle) {
        d.eval();
        const bool ar = d.s_axi_arvalid && d.s_axi_arready;
        const bool response = d.s_axi_rvalid;
        const unsigned status = d.s_axi_rresp;
        const uint32_t data = d.s_axi_rdata;
        s.tick();
        if (ar) d.s_axi_arvalid = 0;
        if (response) { *value = data; return status ? -1 : 0; }
    }
    return -1;
}

#endif

static int run_model(Simulation& simulation, int argc, char **argv) {
    std::ifstream file(argv[1], std::ios::binary);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)), {});
    tiny3tpu_runtime runtime;
    tiny3tpu_mmio io{&simulation, read32, write32, 1000};
    tiny3tpu_qgemm_backend backend{&io, tiny3tpu_mmio_qgemm};
    const tiny3tpu_runtime_model *model;
    tiny3tpu_tensor_view input{}, output{}, tensor{};
    if (!file || bytes.size() > UINT32_MAX ||
        tiny3tpu_runtime_init(&runtime, &backend) ||
        tiny3tpu_runtime_load_model(&runtime, bytes.data(), uint32_t(bytes.size())) ||
        tiny3tpu_runtime_get_model(&runtime, &model)) return 3;
    if (model->header.input_count != 1 || model->header.output_count != 1) return 3;
    for (uint32_t i = 0; i < model->header.tensor_count; ++i) {
        if (tiny3tpu_runtime_get_tensor(&runtime, i, &tensor)) return 3;
        if (tensor.flags & TINY3TPU_TENSOR_INPUT) input = tensor;
        if (tensor.flags & TINY3TPU_TENSOR_OUTPUT) output = tensor;
    }
    if (input.dtype != TINY3TPU_DTYPE_I8 || input.byte_size != uint32_t(argc - 2)) return 3;
    std::vector<int8_t> values(input.byte_size);
    for (uint32_t i = 0; i < input.byte_size; ++i) {
        size_t used;
        const int value = std::stoi(argv[i + 2], &used);
        if (used != std::string(argv[i + 2]).size() || value < -128 || value > 127) return 3;
        values[i] = int8_t(value);
    }
    const uint64_t capacity = uint64_t(model->header.arena_bytes) + model->header.constant_bytes;
    if (capacity > UINT32_MAX) return 3;
    /* Native words guarantee callback output alignment. */
    std::vector<uint32_t> workspace((capacity + 3) / 4);
    std::vector<int32_t> result(output.byte_size / (output.dtype == TINY3TPU_DTYPE_I32 ? 4 : 1));
    if (tiny3tpu_runtime_bind_workspace(&runtime, reinterpret_cast<uint8_t*>(workspace.data()), uint32_t(capacity)) ||
        tiny3tpu_runtime_bind_input(&runtime, input.id, values.data(), uint32_t(values.size())) ||
        tiny3tpu_runtime_run(&runtime) ||
        tiny3tpu_runtime_read_output(&runtime, output.id, result.data(), uint32_t(result.size()))) return 3;
    if (simulation.launches == 0) return 4; // Prove the runtime used RTL.
    for (size_t i = 0; i < result.size(); ++i) std::cout << (i ? " " : "") << result[i];
    std::cout << '\n';
    return 0;
}

int main(int argc, char **argv) {
    Simulation simulation;
    if (argc > 1) return run_model(simulation, argc, argv);
    tiny3tpu_mmio io{&simulation, read32, write32, 1000};
    unsigned cases = 0;
    for (uint32_t m : {1U, 5U, 8U, 9U, 28U}) for (uint32_t k : {1U, 3U, 4U, 7U, 8U, 11U, 17U})
        for (uint32_t n : {1U, 7U}) {
            std::vector<int8_t> a(m * k), b(k * n);
            std::vector<int32_t> out(m * n, INT32_MIN);
            for (unsigned i = 0; i < a.size(); ++i) a[i] = int(i % 17) - 8;
            for (unsigned i = 0; i < b.size(); ++i) b[i] = int(i % 13) - 6;
            simulation.delayed_poll = (cases % 2) != 0;
            if (tiny3tpu_mmio_qgemm(&io, a.data(), b.data(), out.data(), m, k, n)) {
                std::cerr << "MMIO execution failed at case " << cases << '\n'; return 1;
            }
            for (unsigned row = 0; row < m; ++row) for (unsigned col = 0; col < n; ++col) {
                int32_t expected = 0;
                for (unsigned inner = 0; inner < k; ++inner)
                    expected += a[row * k + inner] * b[inner * n + col];
                if (out[row * n + col] != expected) {
                    std::cerr << "result mismatch case " << cases << '\n'; return 2;
                }
            }
            ++cases;
        }
#ifdef TINY3TPU_AXIS_MAILBOX_SIM
    std::cout << "PASS C backend to AXIS mailbox RTL: " << cases << " GEMMs\n";
#else
    std::cout << "PASS C backend to AXI RTL: " << cases << " GEMMs\n";
#endif
}
