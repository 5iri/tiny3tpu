#include "tiny3tpu_compiler.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace tiny3tpu;

int failures = 0;

void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    ++failures;
  }
}

Graph qconv_graph(DType output_dtype = DType::I32,
                  QConv2DParams params = QConv2DParams{1, 1, 0, 0, 0, 0, 1, 1,
                                                       1, 0, 0, 0}) {
  Graph graph;
  graph.tensors = {
      {0, "input", DType::I8, Layout::NHWC, TINY3TPU_TENSOR_INPUT,
       {1, 2, 2, 2}, 1.0f, 0, {}},
      {1, "weight", DType::I8, Layout::Packed, TINY3TPU_TENSOR_CONSTANT,
       {1, 1, 2, 2}, 1.0f, 0, {1, 10, 20, 30}},
      {2, "bias", DType::I32, Layout::Packed, TINY3TPU_TENSOR_CONSTANT,
       {2}, 1.0f, 0, {0, 0}},
      {3, "output", output_dtype, Layout::NHWC, TINY3TPU_TENSOR_OUTPUT,
       {1, 2, 2, 2}, 1.0f, 0, {}},
  };
  graph.inputs = {0};
  graph.outputs = {3};
  graph.operations = {{Opcode::QCONV2D, {0, 1, 2}, {3}, params}};
  return graph;
}

Graph max_pool_graph() {
  Graph graph;
  graph.tensors = {
      {0, "input", DType::I8, Layout::NHWC, TINY3TPU_TENSOR_INPUT,
       {1, 3, 3, 1}, 1.0f, 0, {}},
      {1, "output", DType::I8, Layout::NHWC, TINY3TPU_TENSOR_OUTPUT,
       {1, 1, 1, 1}, 1.0f, 0, {}},
  };
  graph.inputs = {0};
  graph.outputs = {1};
  graph.operations = {{Opcode::MAX_POOL_2D, {0}, {1},
                       MaxPool2DParams{2, 2, 2, 2, 0, 0, 0, 0}}};
  return graph;
}

void check_serialized(const CompiledModel& model, const std::string& name) {
  std::string error;
  check(validate_model_bytes(model.bytes, error), name + " wire validation: " + error);
}

void test_qconv_hwio_and_requantization() {
  const CompiledModel model = compile_graph(qconv_graph());
  check_serialized(model, "QCONV2D");
  ReferenceExecutor executor(model.graph);
  executor.set_input(0, {1, 2, 3, 4, 5, 6, 7, 8});
  const std::vector<int32_t> output = executor.run(3);
  check(output == std::vector<int32_t>({41, 70, 83, 150, 125, 230, 167, 310}),
        "QCONV2D uses NHWC input and HWIO weights");

  Graph requant = qconv_graph(
      DType::I8, QConv2DParams{1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 0,
                               TINY3TPU_QGEMM_FLAG_REQUANT});
  requant.tensors[0].shape = {1, 1, 1, 1};
  requant.tensors[1].shape = {1, 1, 1, 1};
  requant.tensors[1].data = {1};
  requant.tensors[2].shape = {1};
  requant.tensors[2].data = {0};
  requant.tensors[3].shape = {1, 1, 1, 1};
  const CompiledModel requant_model = compile_graph(requant);
  check_serialized(requant_model, "QCONV2D shift-0 requantization");
  ReferenceExecutor requant_executor(requant_model.graph);
  requant_executor.set_input(0, {-2});
  check(requant_executor.run(3) == std::vector<int32_t>({-2}),
        "QCONV2D shift-0 requantization preserves negative sign");
}

void test_max_pool_and_invalid_shapes() {
  const CompiledModel model = compile_graph(max_pool_graph());
  check_serialized(model, "MAX_POOL_2D");
  ReferenceExecutor executor(model.graph);
  executor.set_input(0, {1, 2, 3, 4, 5, 6, 7, 8, 9});
  check(executor.run(1) == std::vector<int32_t>({5}),
        "MAX_POOL_2D uses NHWC window semantics");

  Graph bad_conv = qconv_graph();
  bad_conv.tensors[3].shape[1] = 1;
  check(!validate(bad_conv).empty(), "QCONV2D rejects inconsistent output dimensions");
  try {
    ReferenceExecutor ignored(bad_conv);
    check(false, "reference executor rejects invalid image graph");
  } catch (const std::exception&) {
    check(true, "reference executor rejects invalid image graph");
  }

  Graph bad_pool = max_pool_graph();
  bad_pool.tensors[1].scale = 2.0f;
  check(!validate(bad_pool).empty(), "MAX_POOL_2D rejects scale mismatch");
}

void check_graph_rejected(const Graph& graph, const std::string& name) {
  check(!validate(graph).empty(), name + " graph validation rejects");
  bool compile_rejected = false;
  bool reference_rejected = false;
  try {
    (void)compile_graph(graph);
  } catch (const std::runtime_error&) {
    compile_rejected = true;
  }
  try {
    ReferenceExecutor ignored(graph);
  } catch (const std::runtime_error&) {
    reference_rejected = true;
  }
  check(compile_rejected, name + " compilation rejects");
  check(reference_rejected, name + " reference construction rejects");
}

uint32_t wire_u32(const std::vector<uint8_t>& bytes, size_t offset) {
  uint32_t value = 0;
  for (unsigned i = 0; i < 4; ++i)
    value |= static_cast<uint32_t>(bytes.at(offset + i)) << (8U * i);
  return value;
}

void put_wire_u32(std::vector<uint8_t>& bytes, size_t offset, uint32_t value) {
  for (unsigned i = 0; i < 4; ++i)
    bytes.at(offset + i) = static_cast<uint8_t>(value >> (8U * i));
}

void reseal_wire(std::vector<uint8_t>& bytes) {
  put_wire_u32(bytes, TINY3TPU_HEADER_CRC32_OFFSET, 0);
  uint32_t crc = UINT32_MAX;
  for (uint8_t value : bytes) {
    crc ^= value;
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc >> 1U) ^ ((crc & 1U) ? UINT32_C(0xedb88320) : 0U);
  }
  put_wire_u32(bytes, TINY3TPU_HEADER_CRC32_OFFSET, ~crc);
}

void test_reserved_tensor_id() {
  Graph graph = qconv_graph();
  // Keep the input list and operation reference consistent with the renamed
  // tensor, so rejection cannot be attributed to a dangling reference.
  graph.tensors[0].id = UINT32_MAX - 1U;
  graph.inputs[0] = UINT32_MAX - 1U;
  graph.operations[0].inputs[0] = UINT32_MAX - 1U;
  check(validate(graph).empty(), "largest nonreserved tensor ID is valid");
  const CompiledModel control = compile_graph(graph);
  check_serialized(control, "largest nonreserved tensor ID");
  graph.tensors[0].id = UINT32_MAX;
  graph.inputs[0] = UINT32_MAX;
  graph.operations[0].inputs[0] = UINT32_MAX;
  check_graph_rejected(graph, "reserved tensor ID");

  // Mutate a valid emitted model directly, bypassing graph validation. Refresh
  // CRC so the wire test exercises the reserved-ID rule, not CRC rejection.
  std::vector<uint8_t> bytes = control.bytes;
  const uint32_t tensor_table = wire_u32(bytes, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET);
  const uint32_t operation_table = wire_u32(bytes, TINY3TPU_HEADER_OPERATION_TABLE_OFFSET);
  put_wire_u32(bytes, tensor_table + TINY3TPU_TENSOR_ID_OFFSET, UINT32_MAX);
  put_wire_u32(bytes, operation_table + TINY3TPU_OPERATION_INPUTS_OFFSET, UINT32_MAX);
  reseal_wire(bytes);
  std::string error;
  check(!validate_model_bytes(bytes, error), "wire rejects reserved tensor ID");
  // Restore the control and use the same CRC helper to prove it seals correctly.
  put_wire_u32(bytes, tensor_table + TINY3TPU_TENSOR_ID_OFFSET, UINT32_MAX - 1U);
  put_wire_u32(bytes, operation_table + TINY3TPU_OPERATION_INPUTS_OFFSET, UINT32_MAX - 1U);
  reseal_wire(bytes);
  check(validate_model_bytes(bytes, error), "resealed nonreserved control is valid");
}

void test_int32_tensor_byte_overflow() {
  Graph graph = qconv_graph();
  graph.tensors[1].shape = {1, 1, 1, 1};
  graph.tensors[1].data = {1};
  graph.tensors[2].shape = {1};
  graph.tensors[2].data = {0};
  // Validate metadata only at the boundary; do not allocate a multi-GB arena.
  graph.tensors[0].shape = {1, 1, UINT32_MAX / 4U, 1};
  graph.tensors[3].shape = graph.tensors[0].shape;
  check(validate(graph).empty(), "int32 element count at byte-size boundary is valid");
  for (uint32_t width : {UINT32_MAX / 4U + 1U, UINT32_MAX / 2U}) {
    graph.tensors[0].shape[2] = width;
    graph.tensors[3].shape[2] = width;
    check_graph_rejected(graph, "int32 byte overflow width " + std::to_string(width));
  }
}

} // namespace

int main() {
  try {
    test_qconv_hwio_and_requantization();
    test_max_pool_and_invalid_shapes();
    test_reserved_tensor_id();
    test_int32_tensor_byte_overflow();
  } catch (const std::exception& error) {
    std::cerr << "UNEXPECTED ERROR: " << error.what() << "\n";
    return 1;
  }
  if (failures != 0) return 1;
  std::cout << "all compiler image tests passed\n";
  return 0;
}
