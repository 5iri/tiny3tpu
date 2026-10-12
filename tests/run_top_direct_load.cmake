file(MAKE_DIRECTORY "${BINARY_DIR}")
foreach(size 2 4)
  set(sim "${BINARY_DIR}/top-n${size}.vvp")
  execute_process(COMMAND "${IVERILOG}" -g2012 -Wall -s tb_top_direct_load
    -Ptb_top_direct_load.SMALL_N=${size} -o "${sim}"
    "${SOURCE_DIR}/tests/tb_top_direct_load.sv"
    "${SOURCE_DIR}/multi-core/top.v"
    "${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv"
    "${SOURCE_DIR}/systolic_array/rtl/NxN_systolic_array.v"
    "${SOURCE_DIR}/systolic_array/rtl/pe.v"
    RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 20)
  if(NOT rc STREQUAL "0")
    message(FATAL_ERROR "Direct loading compile failed: ${out}\n${err}")
  endif()
  execute_process(COMMAND "${VVP}" "${sim}"
    RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 20)
  if(NOT rc STREQUAL "0" OR NOT out MATCHES "PASS")
    message(FATAL_ERROR "Direct loading test failed: ${out}\n${err}")
  endif()
  message(STATUS "${out}")
endforeach()
