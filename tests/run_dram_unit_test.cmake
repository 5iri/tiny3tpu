file(MAKE_DIRECTORY "${BINARY_DIR}")
if(NOT DEFINED RTL_DIR)
  set(RTL_DIR "${SOURCE_DIR}/hardware/synapse32")
endif()
execute_process(COMMAND "${IVERILOG}" -g2012 -Wall -s "tb_${MODULE}"
  -o "${BINARY_DIR}/${MODULE}.vvp"
  "${RTL_DIR}/${MODULE}.sv"
  "${SOURCE_DIR}/tests/tb_${MODULE}.sv"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "DDR unit compile: ${out}\n${err}")
endif()
execute_process(COMMAND "${VVP}" "${BINARY_DIR}/${MODULE}.vvp"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0" OR NOT out MATCHES "PASS")
  message(FATAL_ERROR "DDR unit test: ${out}\n${err}")
endif()
message(STATUS "${out}")
