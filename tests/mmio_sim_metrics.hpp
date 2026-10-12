#ifndef TINY3TPU_MMIO_SIM_METRICS_HPP
#define TINY3TPU_MMIO_SIM_METRICS_HPP

#include "tiny3tpu_mmio_backend.h"
#include <cstdint>

// Counts at the driver's register-callback boundary. `ticks` are complete
// simulator clock edges spent inside that callback, including the selected
// transport wrapper but excluding CPU instruction execution.
struct MmioSimCounts {
    uint64_t reads = 0, writes = 0;
    uint64_t operand_writes = 0, operand_ticks = 0;
    uint64_t start_commands = 0, start_ticks = 0;
    uint64_t continue_commands = 0, continue_ticks = 0;
    uint64_t status_reads = 0, status_ticks = 0;
    uint64_t result_selectors = 0, selector_ticks = 0;
    uint64_t result_read_commands = 0, result_command_ticks = 0;
    uint64_t result_low_reads = 0, result_low_ticks = 0;
    uint64_t result_high_reads = 0, result_high_ticks = 0;
    uint64_t result_window_reads = 0, result_window_ticks = 0;
    uint64_t other_reads = 0, other_read_ticks = 0;
    uint64_t other_writes = 0, other_write_ticks = 0;

    uint64_t classified_ticks() const {
        return operand_ticks + start_ticks + continue_ticks + status_ticks +
               selector_ticks + result_command_ticks + result_low_ticks +
               result_high_ticks + result_window_ticks + other_read_ticks + other_write_ticks;
    }

    uint64_t result_register_transactions() const {
        return result_selectors + result_read_commands + result_low_reads +
               result_high_reads + result_window_reads;
    }
};

constexpr uint32_t SIM_REG_CTRL = 0x00;
constexpr uint32_t SIM_REG_CRD_CFG = 0x0c;
constexpr uint32_t SIM_REG_STATUS = 0x10;
constexpr uint32_t SIM_REG_RESULT_LO = 0x14;
constexpr uint32_t SIM_REG_RESULT_HI = 0x18;

template <typename Simulation>
inline void record_write(Simulation& s, uint32_t offset, uint32_t value,
                         uint64_t ticks) {
    auto& c = s.counts;
    ++c.writes;
    if (offset == SIM_REG_CTRL) {
        if (value & (TINY3TPU_MMIO_CTRL_START_CONTINUE ^
                     TINY3TPU_MMIO_CTRL_START)) {
            ++c.continue_commands; c.continue_ticks += ticks;
        } else if (value & TINY3TPU_MMIO_CTRL_START) {
            ++c.start_commands; c.start_ticks += ticks;
        } else if (value == 4U) {
            ++c.result_read_commands; c.result_command_ticks += ticks;
        } else {
            ++c.other_writes; c.other_write_ticks += ticks;
        }
    } else if (offset == SIM_REG_CRD_CFG) {
        ++c.result_selectors; c.selector_ticks += ticks;
    } else if (offset >= 0x40U && offset < 0x80U) {
        ++c.operand_writes; c.operand_ticks += ticks;
    } else {
        ++c.other_writes; c.other_write_ticks += ticks;
    }
}

template <typename Simulation>
inline void record_read(Simulation& s, uint32_t offset, uint32_t value,
                        uint64_t ticks) {
    auto& c = s.counts;
    ++c.reads;
    if (offset == SIM_REG_STATUS) {
        ++c.status_reads; c.status_ticks += ticks;
        s.saw_accum_capability = (value & TINY3TPU_MMIO_STATUS_ACCUM_CAP) != 0;
        s.saw_result_window_capability = (value & TINY3TPU_MMIO_STATUS_RESULT_WINDOW_CAP) != 0;
    } else if (offset == SIM_REG_RESULT_LO) {
        ++c.result_low_reads; c.result_low_ticks += ticks;
    } else if (offset == SIM_REG_RESULT_HI) {
        ++c.result_high_reads; c.result_high_ticks += ticks;
    } else if (offset >= 0x80U && offset <= 0xfcU && (offset & 3U) == 0U) {
        ++c.result_window_reads; c.result_window_ticks += ticks;
    } else {
        ++c.other_reads; c.other_read_ticks += ticks;
    }
}

#endif
