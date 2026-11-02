foreach(required SOURCE_DIR BINARY_DIR IVERILOG VVP)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "Missing ${required}")
  endif()
endforeach()

foreach(size 2 4 8)
  set(work "${BINARY_DIR}/n${size}")
  file(MAKE_DIRECTORY "${work}")
  set(sim "${work}/core.vvp")
  execute_process(
    COMMAND "${IVERILOG}" -g2012 -Wall -s tb_tpu_core_wrapper
      -Ptb_tpu_core_wrapper.N=${size} -o "${sim}"
      "${SOURCE_DIR}/multi-core/tb_tpu_core_wrapper.v"
      "${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv"
      "${SOURCE_DIR}/systolic_array/rtl/NxN_systolic_array.v"
      "${SOURCE_DIR}/systolic_array/rtl/pe.v"
    RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 20)
  if(NOT rc STREQUAL "0")
    message(FATAL_ERROR "Core N=${size} compile failed: ${out}\n${err}")
  endif()
  execute_process(COMMAND "${VVP}" "${sim}" WORKING_DIRECTORY "${work}"
    RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 20)
  if(NOT rc STREQUAL "0" OR NOT out MATCHES "PASS")
    message(FATAL_ERROR "Core N=${size} regression failed: ${out}\n${err}")
  endif()
  message(STATUS "Core N=${size}: ${out}")
endforeach()
