cmake_minimum_required(VERSION 3.16)
project(tiny3tpu_compiler LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(tiny3tpu_compiler STATIC src/compiler.cpp)
target_include_directories(tiny3tpu_compiler PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(tiny3tpu_compiler PRIVATE -Wall -Wextra -Wpedantic)

add_executable(tiny3tpu-compile src/main.cpp)
target_link_libraries(tiny3tpu-compile PRIVATE tiny3tpu_compiler)

add_library(tiny3tpu_runtime STATIC src/runtime.c)
target_include_directories(tiny3tpu_runtime PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(tiny3tpu_runtime PRIVATE -Wall -Wextra -Wpedantic)

add_executable(tiny3tpu-run tools/runtime_run.c)
add_library(tiny3tpu_mmio_backend STATIC src/mmio_backend.c)
target_include_directories(tiny3tpu_mmio_backend PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(tiny3tpu_mmio_backend PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(tiny3tpu-run PRIVATE tiny3tpu_runtime)
target_compile_options(tiny3tpu-run PRIVATE -Wall -Wextra -Wpedantic)

add_library(tiny3tpu_firmware_runtime_adapter STATIC
            src/firmware_runtime_adapter.c)
target_include_directories(tiny3tpu_firmware_runtime_adapter
                           PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(tiny3tpu_firmware_runtime_adapter
                      PUBLIC tiny3tpu_runtime)
target_compile_options(tiny3tpu_firmware_runtime_adapter PRIVATE
                       -Wall -Wextra -Wpedantic)

enable_testing()
add_library(tiny3tpu_axis_mailbox STATIC src/axis_mailbox.c)
target_include_directories(tiny3tpu_axis_mailbox PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(tiny3tpu_axis_mailbox PRIVATE -Wall -Wextra -Wpedantic)
add_executable(tiny3tpu_axis_mailbox_test tests/axis_mailbox_test.c)
target_link_libraries(tiny3tpu_axis_mailbox_test PRIVATE tiny3tpu_axis_mailbox)
add_test(NAME tiny3tpu_axis_mailbox_test COMMAND tiny3tpu_axis_mailbox_test)
add_library(tiny3tpu_firmware_compile_check OBJECT firmware.c)
target_include_directories(tiny3tpu_firmware_compile_check PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/tests/bsp_stubs ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_definitions(tiny3tpu_firmware_compile_check PRIVATE
  TINY3TPU_ENABLE_GENERIC_RUNTIME=1 ENABLE_LWIP_UDP=0)
add_library(tiny3tpu_legacy_firmware_compile_check OBJECT firmware.c)
target_include_directories(tiny3tpu_legacy_firmware_compile_check PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/tests/bsp_stubs)
target_compile_definitions(tiny3tpu_legacy_firmware_compile_check PRIVATE ENABLE_LWIP_UDP=0)
add_executable(tiny3tpu_mmio_backend_test tests/mmio_backend_test.c)
target_link_libraries(tiny3tpu_mmio_backend_test PRIVATE tiny3tpu_mmio_backend)
target_compile_options(tiny3tpu_mmio_backend_test PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_mmio_backend_test COMMAND tiny3tpu_mmio_backend_test)
add_executable(tiny3tpu_tests tests/compiler_tests.cpp)
target_link_libraries(tiny3tpu_tests PRIVATE tiny3tpu_compiler)
target_compile_options(tiny3tpu_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_tests COMMAND tiny3tpu_tests ${CMAKE_CURRENT_SOURCE_DIR}/mnist_int8.json)

add_executable(tiny3tpu_compiler_image_test tests/compiler_image_test.cpp)
target_link_libraries(tiny3tpu_compiler_image_test PRIVATE tiny3tpu_compiler)
target_compile_options(tiny3tpu_compiler_image_test PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_compiler_image_test COMMAND tiny3tpu_compiler_image_test)

add_executable(tiny3tpu_runtime_smoke tests/runtime_smoke.c)
target_link_libraries(tiny3tpu_runtime_smoke PRIVATE tiny3tpu_runtime)
target_compile_options(tiny3tpu_runtime_smoke PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_runtime_smoke COMMAND tiny3tpu_runtime_smoke)

add_executable(tiny3tpu_runtime_requant_test tests/runtime_requant_test.c)
target_link_libraries(tiny3tpu_runtime_requant_test PRIVATE tiny3tpu_runtime)
target_compile_options(tiny3tpu_runtime_requant_test PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_runtime_requant_test COMMAND tiny3tpu_runtime_requant_test)

add_executable(tiny3tpu_runtime_shape_test tests/runtime_shape_test.c)
target_link_libraries(tiny3tpu_runtime_shape_test PRIVATE tiny3tpu_runtime)
target_compile_options(tiny3tpu_runtime_shape_test PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_runtime_shape_test COMMAND tiny3tpu_runtime_shape_test)

add_executable(tiny3tpu_runtime_image_test tests/runtime_image_test.c)
target_link_libraries(tiny3tpu_runtime_image_test PRIVATE tiny3tpu_runtime)
target_compile_options(tiny3tpu_runtime_image_test PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_runtime_image_test COMMAND tiny3tpu_runtime_image_test)

add_executable(tiny3tpu_firmware_runtime_adapter_test
               tests/firmware_runtime_adapter_test.c)
target_link_libraries(tiny3tpu_firmware_runtime_adapter_test
                      PRIVATE tiny3tpu_firmware_runtime_adapter)
target_compile_options(tiny3tpu_firmware_runtime_adapter_test PRIVATE
                       -Wall -Wextra -Wpedantic)
add_test(NAME tiny3tpu_firmware_runtime_adapter_test
         COMMAND tiny3tpu_firmware_runtime_adapter_test)

find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
  add_test(NAME kc705_io_export
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_kc705_io_export.py)
  add_test(NAME synapse32_workload_report
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s tests -p test_synapse32_workload_report.py)
  set_tests_properties(synapse32_workload_report PROPERTIES
                       WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME synapse32_timing_report
           COMMAND ${Python3_EXECUTABLE} -m unittest discover -s tests -p test_synapse32_timing_report.py)
  set_tests_properties(synapse32_timing_report PROPERTIES
                       WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME kc705_route_guard
           COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_kc705_route_guard.py)
  add_test(NAME jax_exporter_smoke
           COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_jax_exporter.py
                   $<TARGET_FILE:tiny3tpu-compile> $<TARGET_FILE:tiny3tpu-run>)
  set_tests_properties(jax_exporter_smoke PROPERTIES SKIP_RETURN_CODE 77)
  add_test(NAME stablehlo_compiler
           COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_stablehlo_compiler.py)
  set_tests_properties(stablehlo_compiler PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 120)
endif()

find_program(TINY3TPU_IVERILOG iverilog)
find_program(TINY3TPU_VERILATOR verilator)
set(TINY3TPU_DDR_PYTHON "" CACHE FILEPATH "Python with pinned LiteDRAM/LiteX 2024.12 for standalone DDR3 tests")
if(TINY3TPU_DDR_PYTHON)
  if(NOT TINY3TPU_VERILATOR)
    message(FATAL_ERROR "Standalone DDR3 engine tests require Verilator")
  endif()
  add_test(NAME kc705_ddr_only
    COMMAND ${TINY3TPU_DDR_PYTHON} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_kc705_ddr_only.py
      --generate --build-dir ${CMAKE_CURRENT_BINARY_DIR}/ddr-only)
  set_tests_properties(kc705_ddr_only PROPERTIES TIMEOUT 180)
endif()
if(TINY3TPU_VERILATOR)
  foreach(mode exp mmio)
    add_test(NAME cordic_${mode}
      COMMAND ${CMAKE_COMMAND} -DVERILATOR=${TINY3TPU_VERILATOR}
        -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
        -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/cordic-${mode}
        -DMMIO=$<STREQUAL:${mode},mmio>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_cordic_test.cmake)
    set_tests_properties(cordic_${mode} PROPERTIES TIMEOUT 120)
  endforeach()
  add_test(NAME rocket_axi_bridge
    COMMAND ${CMAKE_COMMAND} -DVERILATOR=${TINY3TPU_VERILATOR}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/rocket-bridge
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_rocket_bridge_test.cmake)
  set_tests_properties(rocket_axi_bridge PROPERTIES TIMEOUT 120)
  add_test(NAME tiny3tpu_axis_mailbox_rtl
    COMMAND ${CMAKE_COMMAND}
      -DVERILATOR=${TINY3TPU_VERILATOR}
      -DC_COMPILER=${CMAKE_C_COMPILER}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/axis-rtl
      -DAXIS_MAILBOX=ON
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_mmio_rtl_test.cmake)
  set_tests_properties(tiny3tpu_axis_mailbox_rtl PROPERTIES TIMEOUT 180)
  if(Python3_Interpreter_FOUND)
    add_test(NAME stablehlo_axis_rtl
      COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_stablehlo_rtl.py
        --out ${CMAKE_CURRENT_BINARY_DIR}/stablehlo-rtl)
    set_tests_properties(stablehlo_axis_rtl PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 180)
    add_test(NAME jax_axis_fpga_sim
      COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_jax_exporter.py
        $<TARGET_FILE:tiny3tpu-compile>
        ${CMAKE_CURRENT_BINARY_DIR}/axis-rtl/obj/Vsynapse32_tpu_peripheral)
    set_tests_properties(jax_axis_fpga_sim PROPERTIES
      DEPENDS tiny3tpu_axis_mailbox_rtl SKIP_RETURN_CODE 77 TIMEOUT 60)
  endif()
  add_test(NAME tiny3tpu_mmio_rtl
    COMMAND ${CMAKE_COMMAND}
      -DVERILATOR=${TINY3TPU_VERILATOR}
      -DC_COMPILER=${CMAKE_C_COMPILER}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/mmio-rtl
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_mmio_rtl_test.cmake)
  set_tests_properties(tiny3tpu_mmio_rtl PROPERTIES TIMEOUT 180)
  if(Python3_Interpreter_FOUND)
    add_test(NAME jax_fpga_sim
      COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_jax_exporter.py
        $<TARGET_FILE:tiny3tpu-compile>
        ${CMAKE_CURRENT_BINARY_DIR}/mmio-rtl/obj/Vtiny3tpu_axi)
    set_tests_properties(jax_fpga_sim PROPERTIES
      DEPENDS tiny3tpu_mmio_rtl SKIP_RETURN_CODE 77 TIMEOUT 60)
  endif()
endif()
find_program(TINY3TPU_YOSYS yosys)
if(TINY3TPU_YOSYS)
  add_test(NAME tiny3tpu_axis_synthesis
    COMMAND ${TINY3TPU_YOSYS} -Q -T -s tests/check_axis_synthesis.ys)
  set_tests_properties(tiny3tpu_axis_synthesis PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR} TIMEOUT 60)
  add_test(NAME tiny3tpu_axi_synthesis
    COMMAND ${TINY3TPU_YOSYS} -Q -T -s tests/check_axi_synthesis.ys)
  set_tests_properties(tiny3tpu_axi_synthesis PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR} TIMEOUT 60)
endif()
find_program(TINY3TPU_VVP vvp)
if(Python3_Interpreter_FOUND AND TINY3TPU_IVERILOG AND TINY3TPU_VVP AND TINY3TPU_YOSYS)
  add_test(NAME kc705_uberddr3
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_kc705_uberddr3.py
      --yosys ${TINY3TPU_YOSYS} --build-dir ${CMAKE_CURRENT_BINARY_DIR}/uberddr3)
  set_tests_properties(kc705_uberddr3 PROPERTIES TIMEOUT 180)
  add_test(NAME kc705_uberddr3_pipeline
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_kc705_uberddr3.py
      --yosys ${TINY3TPU_YOSYS} --pipeline-bist
      --build-dir ${CMAKE_CURRENT_BINARY_DIR}/uberddr3-pipeline)
  set_tests_properties(kc705_uberddr3_pipeline PROPERTIES TIMEOUT 180)
endif()
if(TINY3TPU_IVERILOG AND TINY3TPU_VVP)
  add_test(NAME tpu_bounded_counters
    COMMAND ${CMAKE_COMMAND}
      -DIVERILOG=${TINY3TPU_IVERILOG} -DVVP=${TINY3TPU_VVP}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/bounded-counters
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_tpu_bounded_counters.cmake)
  set_tests_properties(tpu_bounded_counters PROPERTIES TIMEOUT 90)
  add_test(NAME litedram_wishbone32_to512_rtl
    COMMAND ${CMAKE_COMMAND}
      -DIVERILOG=${TINY3TPU_IVERILOG} -DVVP=${TINY3TPU_VVP}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DRTL_DIR=${CMAKE_CURRENT_SOURCE_DIR}/hardware/kc705_vexriscv
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/dram-unit -DMODULE=litedram_wishbone32_to512
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_dram_unit_test.cmake)
  set_tests_properties(litedram_wishbone32_to512_rtl PROPERTIES TIMEOUT 60)
  add_test(NAME req_resp_cdc_rtl
    COMMAND ${CMAKE_COMMAND}
      -DIVERILOG=${TINY3TPU_IVERILOG} -DVVP=${TINY3TPU_VVP}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DRTL_DIR=${CMAKE_CURRENT_SOURCE_DIR}/hardware/kc705_vexriscv
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/dram-unit -DMODULE=req_resp_cdc
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_dram_unit_test.cmake)
  set_tests_properties(req_resp_cdc_rtl PROPERTIES TIMEOUT 60)
  foreach(module synapse32_memory_sequencer litedram_wishbone_bridge)
    add_test(NAME ${module}_rtl
      COMMAND ${CMAKE_COMMAND}
        -DIVERILOG=${TINY3TPU_IVERILOG} -DVVP=${TINY3TPU_VVP}
        -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
        -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/dram-unit -DMODULE=${module}
        -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_dram_unit_test.cmake)
    set_tests_properties(${module}_rtl PROPERTIES TIMEOUT 60)
  endforeach()
  foreach(module tiny3tpu_axis_bridge synapse32_axis_mailbox synapse32_tpu_mmio)
    add_test(NAME ${module}_rtl
      COMMAND ${CMAKE_COMMAND}
        -DIVERILOG=${TINY3TPU_IVERILOG} -DVVP=${TINY3TPU_VVP}
        -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
        -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/axis-unit -DMODULE=${module}
        -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_axis_unit_test.cmake)
    set_tests_properties(${module}_rtl PROPERTIES TIMEOUT 60)
  endforeach()
  add_test(NAME tiny3tpu_axi_rtl
    COMMAND ${CMAKE_COMMAND}
      -DIVERILOG=${TINY3TPU_IVERILOG}
      -DVVP=${TINY3TPU_VVP}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/rtl
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_rtl_test.cmake)
  set_tests_properties(tiny3tpu_axi_rtl PROPERTIES TIMEOUT 60)
endif()

# Explicit opt-in: the CPU sources are a separate checkout, never copied or edited.
set(TINY3TPU_SYNAPSE32_DIR "" CACHE PATH "Synapse32 checkout for real CPU RTL test")
if(TINY3TPU_SYNAPSE32_DIR)
  if(Python3_Interpreter_FOUND)
    foreach(mode noddr dram interconnect interconnect-pipelined wide cdc)
      add_test(NAME vexriscv_${mode}
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/kc705_vexriscv_sim.py
          ${mode} --synapse32-dir ${TINY3TPU_SYNAPSE32_DIR}
          --out ${CMAKE_CURRENT_BINARY_DIR}/vexriscv-${mode})
      set_tests_properties(vexriscv_${mode} PROPERTIES TIMEOUT 240)
    endforeach()
  endif()
  find_program(TINY3TPU_RISCV_GCC riscv64-unknown-elf-gcc REQUIRED)
  find_program(TINY3TPU_RISCV_OBJCOPY riscv64-unknown-elf-objcopy REQUIRED)
  if(NOT TINY3TPU_VERILATOR OR NOT EXISTS "${TINY3TPU_SYNAPSE32_DIR}/rtl/riscv_cpu.v")
    message(FATAL_ERROR "Synapse32 test requires Verilator and a valid CPU checkout")
  endif()
  add_test(NAME synapse32_cpu_stream
    COMMAND ${CMAKE_COMMAND}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/synapse32-cpu
      -DSYNAPSE32_DIR=${TINY3TPU_SYNAPSE32_DIR}
      -DVERILATOR=${TINY3TPU_VERILATOR}
      -DRISCV_GCC=${TINY3TPU_RISCV_GCC}
      -DRISCV_OBJCOPY=${TINY3TPU_RISCV_OBJCOPY}
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_synapse32_cpu_test.cmake)
  set_tests_properties(synapse32_cpu_stream PROPERTIES TIMEOUT 240)
  add_test(NAME synapse32_cpu_dram
    COMMAND ${CMAKE_COMMAND}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/synapse32-dram
      -DSYNAPSE32_DIR=${TINY3TPU_SYNAPSE32_DIR}
      -DVERILATOR=${TINY3TPU_VERILATOR}
      -DRISCV_GCC=${TINY3TPU_RISCV_GCC}
      -DRISCV_OBJCOPY=${TINY3TPU_RISCV_OBJCOPY}
      -DDRAM_TEST=ON
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_synapse32_cpu_test.cmake)
  set_tests_properties(synapse32_cpu_dram PROPERTIES TIMEOUT 240)
  add_test(NAME synapse32_divider_dram
    COMMAND ${CMAKE_COMMAND}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
      -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/synapse32-divider-dram
      -DSYNAPSE32_DIR=${TINY3TPU_SYNAPSE32_DIR}
      -DCPU_OVERLAY_DIR=${CMAKE_CURRENT_SOURCE_DIR}/hardware/synapse32/experiments/divider
      -DVERILATOR=${TINY3TPU_VERILATOR}
      -DRISCV_GCC=${TINY3TPU_RISCV_GCC}
      -DRISCV_OBJCOPY=${TINY3TPU_RISCV_OBJCOPY}
      -DDRAM_TEST=ON
      -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/run_synapse32_cpu_test.cmake)
  set_tests_properties(synapse32_divider_dram PROPERTIES TIMEOUT 240)
endif()
