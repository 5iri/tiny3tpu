file(MAKE_DIRECTORY "${BINARY_DIR}")
execute_process(COMMAND "${IVERILOG}" -g2012 -s tb_tpu_bounded_counters
  -o "${BINARY_DIR}/test.vvp"
  "${SOURCE_DIR}/tests/tb_tpu_bounded_counters.sv"
  "${SOURCE_DIR}/tests/fixtures/tpu_core_wrapper_integer_counters.sv"
  "${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv"
  "${SOURCE_DIR}/systolic_array/rtl/NxN_systolic_array.v"
  "${SOURCE_DIR}/systolic_array/rtl/pe.v"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "Counter equivalence compile: ${out}\n${err}")
endif()
execute_process(COMMAND "${VVP}" "${BINARY_DIR}/test.vvp"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 60)
if(NOT rc STREQUAL "0" OR NOT out MATCHES "PASS all bounded counter regressions")
  message(FATAL_ERROR "Counter equivalence test: ${out}\n${err}")
endif()
message(STATUS "${out}")
