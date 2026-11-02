file(MAKE_DIRECTORY "${BINARY_DIR}")
execute_process(COMMAND "${IVERILOG}" -g2012 -Wall -s tb_udp_peripheral
  -o "${BINARY_DIR}/udp.vvp" "${SOURCE_DIR}/tests/tb_udp_peripheral.sv"
  "${SOURCE_DIR}/hardware/kc705_vexriscv/tiny3tpu_udp_peripheral.sv"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "UDP peripheral compile failed: ${out}\n${err}")
endif()
execute_process(COMMAND "${VVP}" "${BINARY_DIR}/udp.vvp"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0" OR NOT out MATCHES "PASS")
  message(FATAL_ERROR "UDP peripheral test failed: ${out}\n${err}")
endif()
message(STATUS "${out}")
