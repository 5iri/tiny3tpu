# Invoke with -DSOURCE_DIR=... -DBINARY_DIR=... and optional
# -DIVERILOG=... -DVVP=... before -P tests/run_rtl_test.cmake.
if(NOT DEFINED SOURCE_DIR)
  get_filename_component(SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
endif()
if(NOT DEFINED BINARY_DIR)
  set(BINARY_DIR "${CMAKE_CURRENT_BINARY_DIR}/rtl-test")
endif()
if(NOT DEFINED IVERILOG)
  find_program(IVERILOG iverilog REQUIRED)
endif()
if(NOT DEFINED VVP)
  find_program(VVP vvp REQUIRED)
endif()
file(MAKE_DIRECTORY "${BINARY_DIR}")
set(sim "${BINARY_DIR}/tb_tiny3tpu_axi.vvp")
execute_process(
  COMMAND "${IVERILOG}" -g2012 -Wall -s tb_tiny3tpu_axi -o "${sim}"
          "${SOURCE_DIR}/multi-core/tb_tiny3tpu_axi.sv"
          "${SOURCE_DIR}/multi-core/tiny3tpu_axi.sv"
          "${SOURCE_DIR}/multi-core/top.v"
          "${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv"
          "${SOURCE_DIR}/systolic_array/rtl/NxN_systolic_array.v"
          "${SOURCE_DIR}/systolic_array/rtl/pe.v"
  RESULT_VARIABLE compile_result OUTPUT_VARIABLE compile_out
  ERROR_VARIABLE compile_err TIMEOUT 60)
if(NOT compile_result STREQUAL "0")
  message(FATAL_ERROR "Icarus compile failed (${compile_result}):\n${compile_out}\n${compile_err}")
endif()
execute_process(COMMAND "${VVP}" "${sim}"
  RESULT_VARIABLE run_result OUTPUT_VARIABLE run_out
  ERROR_VARIABLE run_err TIMEOUT 60)
if(NOT run_result STREQUAL "0" OR NOT run_out MATCHES "PASS tiny3tpu_axi:")
  message(FATAL_ERROR "RTL test failed (${run_result}):\n${run_out}\n${run_err}")
endif()
message(STATUS "${run_out}")
