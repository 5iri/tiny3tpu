file(MAKE_DIRECTORY "${BINARY_DIR}")
execute_process(COMMAND "${VERILATOR}" --cc --exe --build -j 2 -Wno-fatal
  --top-module axi64_to_wb32 --Mdir "${BINARY_DIR}/obj"
  "${SOURCE_DIR}/hardware/kc705_rocket/axi64_to_wb32.sv"
  "${SOURCE_DIR}/tests/rocket_axi_bridge_test.cpp"
  RESULT_VARIABLE result OUTPUT_FILE "${BINARY_DIR}/build.log" ERROR_FILE "${BINARY_DIR}/build-errors.log")
if(NOT result EQUAL 0)
  message(FATAL_ERROR "Rocket bridge build failed; see ${BINARY_DIR}")
endif()
execute_process(COMMAND "${BINARY_DIR}/obj/Vaxi64_to_wb32" RESULT_VARIABLE result)
if(NOT result EQUAL 0)
  message(FATAL_ERROR "Rocket bridge test failed")
endif()
