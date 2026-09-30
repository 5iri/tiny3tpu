foreach(required SOURCE_DIR BINARY_DIR VERILATOR C_COMPILER)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "Missing ${required}")
  endif()
endforeach()
file(MAKE_DIRECTORY "${BINARY_DIR}")
set(rtl_top tiny3tpu_axi)
set(extra_sources)
set(extra_cflags "")
set(extra_ldflags "")
set(pass_pattern "PASS C backend to AXI RTL:")
if(AXIS_MAILBOX)
  set(rtl_top synapse32_tpu_peripheral)
  set(extra_sources
    "${SOURCE_DIR}/multi-core/synapse32_tpu_peripheral.sv"
    "${SOURCE_DIR}/multi-core/synapse32_axis_mailbox.sv"
    "${SOURCE_DIR}/multi-core/tiny3tpu_axis.sv"
    "${SOURCE_DIR}/multi-core/tiny3tpu_axis_bridge.sv")
  set(extra_cflags "-DTINY3TPU_AXIS_MAILBOX_SIM=1")
  set(extra_ldflags "${BINARY_DIR}/axis_mailbox.o")
  set(pass_pattern "PASS C backend to AXIS mailbox RTL:")
  execute_process(COMMAND "${C_COMPILER}" -std=c11 -Wall -Wextra -Werror -pedantic
    -I${SOURCE_DIR}/include -c "${SOURCE_DIR}/src/axis_mailbox.c"
    -o "${BINARY_DIR}/axis_mailbox.o" RESULT_VARIABLE rc
    OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
  if(NOT rc STREQUAL "0")
    message(FATAL_ERROR "Mailbox C driver compile failed: ${out}\n${err}")
  endif()
endif()
execute_process(COMMAND "${C_COMPILER}" -std=c11 -Wall -Wextra -Werror -pedantic
  -I${SOURCE_DIR}/include -c "${SOURCE_DIR}/src/mmio_backend.c"
  -o "${BINARY_DIR}/mmio_backend.o" RESULT_VARIABLE rc
  OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "C backend compile failed: ${out}\n${err}")
endif()
execute_process(COMMAND "${C_COMPILER}" -std=c11 -Wall -Wextra -Werror -pedantic
  -I${SOURCE_DIR}/include -c "${SOURCE_DIR}/src/runtime.c"
  -o "${BINARY_DIR}/runtime.o" RESULT_VARIABLE rc
  OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "C runtime compile failed: ${out}\n${err}")
endif()
execute_process(COMMAND "${VERILATOR}" --cc --exe --build -j 2 -Wno-fatal
  --top-module ${rtl_top} --Mdir "${BINARY_DIR}/obj"
  -CFLAGS "-I${SOURCE_DIR}/include ${extra_cflags}"
  -LDFLAGS "${BINARY_DIR}/mmio_backend.o ${BINARY_DIR}/runtime.o ${extra_ldflags} -lm"
  ${extra_sources}
  "${SOURCE_DIR}/multi-core/tiny3tpu_axi.sv"
  "${SOURCE_DIR}/multi-core/top.v"
  "${SOURCE_DIR}/multi-core/tpu_core_wrapper.sv"
  "${SOURCE_DIR}/systolic_array/rtl/NxN_systolic_array.v"
  "${SOURCE_DIR}/systolic_array/rtl/pe.v"
  "${SOURCE_DIR}/tests/mmio_rtl_test.cpp"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 120)
if(NOT rc STREQUAL "0")
  message(FATAL_ERROR "Verilator build failed: ${out}\n${err}")
endif()
execute_process(COMMAND "${BINARY_DIR}/obj/V${rtl_top}"
  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err TIMEOUT 30)
if(NOT rc STREQUAL "0" OR NOT out MATCHES "${pass_pattern}")
  message(FATAL_ERROR "C/RTL integration failed: ${out}\n${err}")
endif()
message(STATUS "${out}")
