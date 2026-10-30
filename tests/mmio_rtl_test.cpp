#ifndef TINY3TPU_AXIS_MAILBOX_SIM
#include "Vtiny3tpu_axi.h"
#endif
#include "tiny3tpu_mmio_backend.h"
#include "mmio_sim_metrics.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <fstream>
#include <iterator>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#ifdef TINY3TPU_AXIS_MAILBOX_SIM
#include "axis_mailbox_sim.hpp"
#else
struct Simulation {
    Vtiny3tpu_axi dut;
    bool delayed_poll = false;
    bool mask_accum_capability = false;
    bool mask_result_window_capability = false;
    unsigned launches = 0;
    MmioSimCounts counts;
    uint64_t simulated_ticks = 0;
    bool saw_accum_capability = false;
    bool saw_result_window_capability = false;
    void tick() {
        dut.s_axi_aclk = 0; dut.eval();
        dut.s_axi_aclk = 1; dut.eval();
        dut.s_axi_aclk = 0; dut.eval();
        ++simulated_ticks;
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
    const uint64_t begin = s.simulated_ticks;
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
            const uint64_t elapsed = s.simulated_ticks - begin;
            if (status == 0) record_write(s, offset, value, elapsed);
            if (status == 0 && offset == SIM_REG_CTRL &&
                (value & TINY3TPU_MMIO_CTRL_START)) ++s.launches;
            if (offset == SIM_REG_CTRL &&
                (value & TINY3TPU_MMIO_CTRL_START) && s.delayed_poll)
                for (unsigned i = 0; i < 500; ++i) s.tick();
            return status ? -1 : 0;
        }
    }
    return -1;
}

static int read32(void *user, uint32_t offset, uint32_t *value) {
    auto& s = *static_cast<Simulation*>(user);
    auto& d = s.dut;
    const uint64_t begin = s.simulated_ticks;
    d.s_axi_araddr = offset; d.s_axi_arvalid = 1;
    for (unsigned cycle = 0; cycle < 100; ++cycle) {
        d.eval();
        const bool ar = d.s_axi_arvalid && d.s_axi_arready;
        const bool response = d.s_axi_rvalid;
        const unsigned status = d.s_axi_rresp;
        uint32_t data = d.s_axi_rdata;
        s.tick();
        if (ar) d.s_axi_arvalid = 0;
        if (response) {
            if (status) return -1;
            if (offset == SIM_REG_STATUS && s.mask_accum_capability)
                data &= ~TINY3TPU_MMIO_STATUS_ACCUM_CAP;
            if (offset == SIM_REG_STATUS && s.mask_result_window_capability)
                data &= ~TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP;
            *value = data;
            record_read(s, offset, data, s.simulated_ticks - begin);
            return 0;
        }
    }
    return -1;
}

#endif

static int run_model(Simulation& simulation, int argc, char **argv) {
    std::ifstream file(argv[1], std::ios::binary);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)), {});
    tiny3tpu_runtime runtime;
    tiny3tpu_mmio io{&simulation, read32, write32, 1000};
    tiny3tpu_qgemm_backend backend{&io, tiny3tpu_mmio_qgemm, tiny3tpu_mmio_qgemm_packed, nullptr};
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

struct ProfileResult {
    std::string name;
    uint32_t m, k, n, repetitions;
    bool advertised;
    uint64_t ticks;
    unsigned launches;
    MmioSimCounts counts;
    uint64_t outputs_checked;
    std::vector<int32_t> result;
};

static bool measure_case(const std::string& name, uint32_t m, uint32_t k,
                         uint32_t n, uint32_t repetitions, bool advertised,
                         bool result_window, ProfileResult& result) {
    Simulation simulation;
    simulation.mask_accum_capability = !advertised;
    simulation.mask_result_window_capability = !result_window;
    tiny3tpu_mmio io{&simulation, read32, write32, 1000};
    std::vector<int8_t> a(size_t(m) * k), b(size_t(k) * n);
    for (size_t i = 0; i < a.size(); ++i) a[i] = int8_t(int(i % 17) - 8);
    for (size_t i = 0; i < b.size(); ++i) b[i] = int8_t(int(i % 13) - 6);
    std::vector<int32_t> output(size_t(m) * n);
    uint64_t checked = 0;
    const uint64_t begin = simulation.simulated_ticks;
    for (uint32_t rep = 0; rep < repetitions; ++rep) {
        std::fill(output.begin(), output.end(), INT32_MIN);
        if (tiny3tpu_mmio_qgemm(&io, a.data(), b.data(), output.data(), m, k, n))
            return false;
        for (uint32_t row = 0; row < m; ++row) {
            for (uint32_t col = 0; col < n; ++col) {
                int64_t expected = 0;
                for (uint32_t inner = 0; inner < k; ++inner)
                    expected += int32_t(a[size_t(row) * k + inner]) *
                                int32_t(b[size_t(inner) * n + col]);
                if (expected < INT32_MIN || expected > INT32_MAX ||
                    output[size_t(row) * n + col] != int32_t(expected))
                    return false;
                ++checked;
            }
        }
    }
    result = {name, m, k, n, repetitions, advertised,
              simulation.simulated_ticks - begin, simulation.launches,
              simulation.counts, checked, output};
    if (simulation.saw_accum_capability != advertised ||
        simulation.saw_result_window_capability != result_window ||
        advertised != !simulation.mask_accum_capability)
        return false;
    return true;
}

static void print_counts(const MmioSimCounts& c) {
    std::cout << "{\"reads\":" << c.reads << ",\"writes\":" << c.writes
              << ",\"ticks_by_register_class\":{"
              << "\"operand_writes\":{" << "\"transactions\":" << c.operand_writes << ",\"ticks\":" << c.operand_ticks << "},"
              << "\"start_commands\":{" << "\"transactions\":" << c.start_commands << ",\"ticks\":" << c.start_ticks << "},"
              << "\"continue_commands\":{" << "\"transactions\":" << c.continue_commands << ",\"ticks\":" << c.continue_ticks << "},"
              << "\"status_reads\":{" << "\"transactions\":" << c.status_reads << ",\"ticks\":" << c.status_ticks << "},"
              << "\"result_selectors\":{" << "\"transactions\":" << c.result_selectors << ",\"ticks\":" << c.selector_ticks << "},"
              << "\"result_read_commands\":{" << "\"transactions\":" << c.result_read_commands << ",\"ticks\":" << c.result_command_ticks << "},"
              << "\"result_low_reads\":{" << "\"transactions\":" << c.result_low_reads << ",\"ticks\":" << c.result_low_ticks << "},"
              << "\"result_high_reads\":{" << "\"transactions\":" << c.result_high_reads << ",\"ticks\":" << c.result_high_ticks << "},"
              << "\"result_window_reads\":{" << "\"transactions\":" << c.result_window_reads << ",\"ticks\":" << c.result_window_ticks << "},"
              << "\"other_reads\":{" << "\"transactions\":" << c.other_reads << ",\"ticks\":" << c.other_read_ticks << "},"
              << "\"other_writes\":{" << "\"transactions\":" << c.other_writes << ",\"ticks\":" << c.other_write_ticks << "}}}";
}

static bool print_profile() {
    struct Workload {
        const char *name;
        uint32_t m, k, n, repetitions;
        uint64_t legacy_result_register_transactions;
        uint64_t accumulated_result_register_transactions;
    };
    // Repetition counts reflect matrix calls: one FC per image, six GEMMs per
    // attention block, and one transform per captured frame/request.
    const Workload workloads[] = {
        {"mnist_fc", 1, 784, 10, 1, 7840, 80},
        {"attention_block", 8, 8, 8, 6, 3072, 1536},
        {"banana_transform", 204, 3, 3, 1, 2448, 2448},
        {"cloth_camera_transform", 28, 3, 3, 1, 336, 336},
    };
    std::vector<std::array<ProfileResult, 3>> rows;
    for (const auto& w : workloads) {
        ProfileResult legacy{}, accumulated{}, window{};
        if (!measure_case(w.name, w.m, w.k, w.n, w.repetitions, false, false, legacy) ||
            !measure_case(w.name, w.m, w.k, w.n, w.repetitions, true, false, accumulated) ||
            !measure_case(w.name, w.m, w.k, w.n, w.repetitions, true, true, window))
            return false;
        if (legacy.launches != accumulated.launches ||
            legacy.outputs_checked != accumulated.outputs_checked ||
            legacy.result != accumulated.result ||
            legacy.counts.continue_commands != 0 ||
            legacy.counts.classified_ticks() != legacy.ticks ||
            accumulated.counts.classified_ticks() != accumulated.ticks ||
            legacy.counts.result_register_transactions() !=
                w.legacy_result_register_transactions ||
            accumulated.counts.result_register_transactions() !=
                w.accumulated_result_register_transactions)
            return false;
        // These selected K>4 fixtures span multiple reduction launches under
        // the current two-core tile schedule; the capability path should defer
        // their intermediate results while keeping launch counts unchanged.
        if (w.k > 4 &&
            (accumulated.counts.continue_commands == 0 ||
             accumulated.counts.result_read_commands >= legacy.counts.result_read_commands))
            return false;
        if (w.k <= 4 &&
            (accumulated.counts.continue_commands != 0 ||
             legacy.counts.result_selectors != accumulated.counts.result_selectors ||
             legacy.counts.result_read_commands != accumulated.counts.result_read_commands ||
             legacy.counts.result_low_reads != accumulated.counts.result_low_reads ||
             legacy.counts.result_high_reads != accumulated.counts.result_high_reads))
            return false;
        if (window.result != accumulated.result || window.launches != accumulated.launches ||
            window.outputs_checked != accumulated.outputs_checked ||
            window.counts.classified_ticks() != window.ticks ||
            window.counts.result_window_reads != w.accumulated_result_register_transactions/4 ||
            window.counts.result_register_transactions() != window.counts.result_window_reads)
            return false;
        rows.push_back({legacy, accumulated, window});
    }

    std::cout << "{\"schema\":\"tiny3tpu-rtl-qgemm-profile-v2\","
              << "\"scope\":\"Host-executed C QGEMM driver against simulated accelerator RTL; ticks cover callback register transactions and their AXI/AXIS transport; excludes VexRiscv CPU execution, physical board latency and UART\","
              << "\"comparison\":\"same updated RTL and operands; legacy masks bits 8 and 9, accumulation-only masks bit 9, result-window mode exposes both. No old-RTL timing is simulated\","
              << "\"workloads\":[";
    for (size_t i = 0; i < rows.size(); ++i) {
        const auto& a = rows[i][0];
        const auto& b = rows[i][1];
        const auto& c = rows[i][2];
        if (i) std::cout << ',';
        std::cout << "{\"name\":\"" << a.name << "\",\"m\":" << a.m
                  << ",\"k\":" << a.k << ",\"n\":" << a.n
                  << ",\"repetitions\":" << a.repetitions
                  << ",\"arithmetic\":\"signed int8 x int8, int32 checked output\","
                  << "\"legacy_and_accumulated_outputs_equal\":true,"
                  << "\"all_modes_outputs_equal\":true,"
                  << "\"results_checked_per_mode\":" << a.outputs_checked
                  << ",\"legacy_masked_capability\":{\"simulated_ticks\":" << a.ticks
                  << ",\"launches\":" << a.launches << ",\"register_transactions\":";
        print_counts(a.counts);
        std::cout << "},\"accumulation_capable\":{\"simulated_ticks\":" << b.ticks
                  << ",\"launches\":" << b.launches << ",\"register_transactions\":";
        print_counts(b.counts);
        std::cout << "},\"result_window_capable\":{\"simulated_ticks\":" << c.ticks
                  << ",\"launches\":" << c.launches << ",\"register_transactions\":";
        print_counts(c.counts);
        std::cout << "}}";
    }
    std::cout << "]}\n";
    return true;
}

int main(int argc, char **argv) {
    if (argc == 2 && std::string(argv[1]) == "--profile")
        return print_profile() ? 0 : 5;
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
