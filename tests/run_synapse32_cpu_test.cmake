foreach(required SOURCE_DIR BINARY_DIR SYNAPSE32_DIR VERILATOR RISCV_GCC RISCV_OBJCOPY)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "Missing ${required}")
  endif()
endforeach()
# Deliberately exclude Synapse32 top.v and all experimental board/MMU wrappers.
file(GLOB cpu_modules "${SYNAPSE32_DIR}/rtl/core_modules/*.v"
                      "${SYNAPSE32_DIR}/rtl/pipeline_stages/*.v")
list(APPEND cpu_modules "${SYNAPSE32_DIR}/rtl/riscv_cpu.v"
     "${SYNAPSE32_DIR}/rtl/execution_unit.v"
     "${SYNAPSE32_DIR}/rtl/memory_unit.v" "${SYNAPSE32_DIR}/rtl/writeback.v")
if(CPU_OVERLAY_DIR)
  foreach(name riscv_cpu execution_unit alu divider)
    set(matches)
    foreach(source IN LISTS cpu_modules)
      get_filename_component(filename "${source}" NAME)
      if(filename STREQUAL "${name}.v")
        list(APPEND matches "${source}")
      endif()
    endforeach()
    list(LENGTH matches count)
    if(NOT count EQUAL 1 OR NOT EXISTS "${CPU_OVERLAY_DIR}/${name}.v"
       OR IS_DIRECTORY "${CPU_OVERLAY_DIR}/${name}.v")
      message(FATAL_ERROR "Incomplete CPU overlay: ${name}")
    endif()
    list(REMOVE_ITEM cpu_modules ${matches})
    list(APPEND cpu_modules "${CPU_OVERLAY_DIR}/${name}.v")
  endforeach()
endif()
file(MAKE_DIRECTORY "${BINARY_DIR}")
set(extra_firmware)
set(extra_flags)
set(extra_rtl)
set(rtl_top synapse32_cpu_fixture)
set(harness "${SOURCE_DIR}/tests/synapse32_cpu_test.cpp")
set(pass_pattern "PASS Synapse32 CPU -> AXIS -> TPU:")
if(DRAM_TEST)
  set(extra_flags -DTINY3TPU_DRAM_SMOKE)
  set(extra_firmware "${SOURCE_DIR}/hardware/synapse32/dram_selftest.c")
  set(rtl_top synapse32_dram_soc)
  set(harness "${SOURCE_DIR}/tests/synapse32_dram_test.cpp")
  set(pass_pattern "PASS Synapse32 variable-latency DRAM -> TPU:")
  set(extra_rtl
    -DSYNAPSE32_CLOCK_SIM
    "-GBOOT_HEX=\"${BINARY_DIR}/smoke.hex\""
    "${SOURCE_DIR}/hardware/synapse32/synapse32_clock_enable.sv"
    "${SOURCE_DIR}/hardware/synapse32/synapse32_memory_sequencer.sv"
    "${SOURCE_DIR}/hardware/synapse32/synapse32_dram_soc.sv")
endif()
execute_process(COMMAND "${RISCV_GCC}" -march=rv32i_zicsr_zifencei -mabi=ilp32
  -Os -ffreestanding -fno-builtin -nostdlib -msmall-data-limit=0
  -Wall -Wextra -Werror -I${SOURCE_DIR}/include
  -Wl,--no-relax -T${SOURCE_DIR}/hardware/synapse32/bringup.ld
  "${SOURCE_DIR}/hardware/synapse32/start.S"
  "${SOURCE_DIR}/hardware/synapse32/stream_smoke.c"
  ${extra_flags} ${extra_firmware}
  "${SOURCE_DIR}/src/axis_mailbox.c" "${SOURCE_DIR}/src/mmio_backend.c"
  -lgcc -o "${BINARY_DIR}/smoke.elf"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "RV32 firmware build failed: ${out}\n${err}")
endif()
execute_process(COMMAND "${RISCV_OBJCOPY}" -O binary
  "${BINARY_DIR}/smoke.elf" "${BINARY_DIR}/smoke.bin"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "RV32 image failed: ${out}\n${err}")
endif()
if(DRAM_TEST)
  execute_process(COMMAND "${RISCV_OBJCOPY}" -O verilog --verilog-data-width=4
    --change-addresses=-0x80000000
    "${BINARY_DIR}/smoke.elf" "${BINARY_DIR}/smoke.hex"
    RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
  if(NOT rc STREQUAL "0")
    message(FATAL_ERROR "Boot memory image failed: ${out}\n${err}")
  endif()
endif()
execute_process(COMMAND "${VERILATOR}" --cc --exe --build -j 2 -Wno-fatal
  --top-module ${rtl_top} --Mdir "${BINARY_DIR}/obj"
  -I${SYNAPSE32_DIR}/rtl/include
  ${cpu_modules}
  ${extra_rtl}
  "${SOURCE_DIR}/tests/synapse32_cpu_fixture.sv"
  "${SOURCE_DIR}/multi-core/synapse32_tpu_mmio.sv"
  "${SOURCE_DIR}/multi-core/synapse32_tpu_peripheral.sv"
  "${SOURCE_DIR}/multi-core/synapse32_axis_mailbox.sv"
  "${SOURCE_DIR}/multi-core/tiny3tpu_axis.sv"
  "${SOURCE_DIR}/multi-core/tiny3tpu_axis_bridge.sv"
  "${SOURCE_DIR}/multi-core/tiny3tpu_axi.sv"
  "${SOURCE_DIR}/multi-core/top.v"
  "${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv"
  "${SOURCE_DIR}/systolic_array/rtl/NxN_systolic_array.v"
  "${SOURCE_DIR}/systolic_array/rtl/pe.v"
  "${harness}"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 120)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "Synapse32 Verilator build failed: ${out}\n${err}")
endif()
execute_process(COMMAND "${BINARY_DIR}/obj/V${rtl_top}" "${BINARY_DIR}/smoke.bin"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 60)
if(NOT rc STREQUAL "0" OR NOT out MATCHES "${pass_pattern}")
  message(FATAL_ERROR "Synapse32 CPU test failed: ${out}\n${err}")
endif()
message(STATUS "${out}")
if(DRAM_TEST AND NOT out MATCHES "METRICS [{]")
  message(FATAL_ERROR "Synapse32 DRAM workload did not emit metrics")
endif()
