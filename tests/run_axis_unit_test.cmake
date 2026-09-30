foreach(required SOURCE_DIR BINARY_DIR IVERILOG VVP MODULE)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "Missing ${required}")
  endif()
endforeach()
file(MAKE_DIRECTORY "${BINARY_DIR}")
set(sim "${BINARY_DIR}/tb_${MODULE}.vvp")
set(extra_sources)
if(MODULE STREQUAL "synapse32_tpu_mmio")
  set(extra_sources
    "${SOURCE_DIR}/multi-core/synapse32_tpu_peripheral.sv"
    "${SOURCE_DIR}/multi-core/synapse32_axis_mailbox.sv"
    "${SOURCE_DIR}/multi-core/tiny3tpu_axis.sv"
    "${SOURCE_DIR}/multi-core/tiny3tpu_axis_bridge.sv"
    "${SOURCE_DIR}/multi-core/tiny3tpu_axi.sv"
    "${SOURCE_DIR}/multi-core/top.v"
    "${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv"
    "${SOURCE_DIR}/systolic_array/rtl/NxN_systolic_array.v"
    "${SOURCE_DIR}/systolic_array/rtl/pe.v")
endif()
execute_process(COMMAND "${IVERILOG}" -g2012 -Wall -s "tb_${MODULE}" -o "${sim}"
  "${SOURCE_DIR}/multi-core/tb_${MODULE}.sv"
  "${SOURCE_DIR}/multi-core/${MODULE}.sv"
  ${extra_sources}
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "Stream unit compile failed: ${out}\n${err}")
endif()
execute_process(COMMAND "${VVP}" "${sim}"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0" OR NOT out MATCHES "PASS")
  message(FATAL_ERROR "Stream unit test failed: ${out}\n${err}")
endif()
message(STATUS "${out}")
