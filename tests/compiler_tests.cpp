#include "tiny3tpu_compiler.hpp"

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
int failures = 0;

void check(bool condition, const std::string& message) {
  if (!condition) { std::cerr << "FAIL: " << message << "\n"; ++failures; }
}
template <typename Fn>
void expect_throw(Fn&& fn, const std::string& message) {
  try { fn(); check(false, message + " (did not throw)"); }
  catch (const std::exception&) { check(true, message); }
}
uint32_t u32(const std::vector<uint8_t>& bytes, size_t offset) {
  return uint32_t(bytes[offset]) | (uint32_t(bytes[offset + 1]) << 8) |
         (uint32_t(bytes[offset + 2]) << 16) | (uint32_t(bytes[offset + 3]) << 24);
}
void put_u32(std::vector<uint8_t>& bytes, size_t offset, uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) bytes[offset + i] = static_cast<uint8_t>(value >> (8 * i));
}
uint32_t crc32(const std::vector<uint8_t>& bytes) {
  uint32_t crc = 0xffffffffU;
  for (uint8_t byte : bytes) {
    crc ^= byte;
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
  }
  return ~crc;
}
void refresh_crc(std::vector<uint8_t>& bytes) {
  put_u32(bytes, TINY3TPU_HEADER_CRC32_OFFSET, 0);
  put_u32(bytes, TINY3TPU_HEADER_CRC32_OFFSET, crc32(bytes));
}
bool contains(const std::string& text, const std::string& needle) {
  return text.find(needle) != std::string::npos;
}

void check_compiled_graph_validates(const tiny3tpu::Graph& graph, const std::string& name) {
  const tiny3tpu::CompiledModel model = tiny3tpu::compile_graph(graph);
  std::string error;
  check(tiny3tpu::validate(model.graph).empty(), name + " graph validates before serialization");
  check(tiny3tpu::validate_model_bytes(model.bytes, error), name + " compiled bytes validate: " + error);
}

tiny3tpu::Graph qgemm_graph() {
  using namespace tiny3tpu;
  Graph graph;
  graph.tensors = {
      Tensor{0, "input", DType::I8, Layout::Packed, TINY3TPU_TENSOR_INPUT, {2}, 1.0f, 0, {}},
      Tensor{1, "weight", DType::I8, Layout::Packed, TINY3TPU_TENSOR_CONSTANT, {2, 2}, 1.0f, 0, {2, 0, 0, -1}},
      Tensor{2, "bias", DType::I32, Layout::Packed, TINY3TPU_TENSOR_CONSTANT, {2}, 1.0f, 0, {1, 2}},
      Tensor{3, "output", DType::I32, Layout::Packed, TINY3TPU_TENSOR_OUTPUT, {2}, 1.0f, 0, {}},
  };
  graph.inputs = {0};
  graph.outputs = {3};
  graph.operations.push_back(Operation{Opcode::QGEMM, {0, 1, 2}, {3}, QGemmParams{0, 0, 0}});
  return graph;
}

void test_abi_and_executor() {
  using namespace tiny3tpu;
  const Graph graph = qgemm_graph();
  const CompiledModel first = compile_graph(graph);
  const CompiledModel second = compile_graph(graph);
  check(first.bytes == second.bytes, "serialization is deterministic");
  std::string error;
  check(validate_model_bytes(first.bytes, error), "serialized model validates: " + error);
  check(u32(first.bytes, 8) == TINY3TPU_MODEL_HEADER_BYTES, "header size is explicit");
  check(u32(first.bytes, 16) == 4 && u32(first.bytes, 20) == 1, "header counts decode independently");
  check(u32(first.bytes, 36) == 16, "QGEMM parameter record size is explicit");
  check(u32(first.bytes, 52) >= 32, "activation arena is present and bounded");

  ReferenceExecutor executor(first.graph);
  executor.set_input(0, {3, -4});
  check(executor.run(3) == std::vector<int32_t>({7, 6}), "QGEMM reference arithmetic");
  expect_throw([&] { executor.set_input(0, {1}); }, "input length mismatch rejected");

  std::vector<uint8_t> corrupt = first.bytes;
  corrupt.back() ^= 1;
  check(!validate_model_bytes(corrupt, error) && error == "CRC mismatch", "CRC corruption rejected");
  corrupt = first.bytes;
  corrupt[24] = 0;
  check(!validate_model_bytes(corrupt, error), "table offset corruption rejected");
}

void test_qgemm_wire_semantics_and_constant_safety() {
  using namespace tiny3tpu;
  const CompiledModel model = compile_graph(qgemm_graph());
  const uint32_t tensor_table = u32(model.bytes, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET);
  const uint32_t parameter_offset = u32(model.bytes, TINY3TPU_HEADER_PARAMETER_OFFSET);
  const uint32_t bias_record = tensor_table + 2 * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
  const uint32_t output_record = tensor_table + 3 * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
  std::string error;

  std::vector<uint8_t> malformed = model.bytes;
  put_u32(malformed, parameter_offset + 4, 64);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error), "QGEMM shift 64 rejected after CRC refresh");

  malformed = model.bytes;
  put_u32(malformed, parameter_offset + 8, UINT32_C(0x80000000));
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error), "unknown QGEMM flags rejected after CRC refresh");

  malformed = model.bytes;
  malformed[bias_record + 4] = TINY3TPU_DTYPE_I8;
  put_u32(malformed, bias_record + TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, 2);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error), "wrong QGEMM bias dtype rejected after CRC refresh");

  malformed = model.bytes;
  put_u32(malformed, output_record + TINY3TPU_TENSOR_DIMS_OFFSET, 3);
  put_u32(malformed, output_record + TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, 12);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "shapes"),
        "incompatible QGEMM output shape rejected after CRC refresh with shape diagnostic");

  Graph missing_constant = qgemm_graph();
  missing_constant.tensors[1].data.clear();
  expect_throw([&] { (void)compile_graph(missing_constant); },
               "missing QGEMM constant data rejected without dereference");
}

void test_graph_flag_contracts() {
  using namespace tiny3tpu;

  Graph output_is_input = qgemm_graph();
  output_is_input.tensors[0].flags |= TINY3TPU_TENSOR_OUTPUT;
  output_is_input.outputs = {0};
  auto errors = validate(output_is_input);
  check(std::any_of(errors.begin(), errors.end(), [](const std::string& error) {
          return contains(error, "output cannot also be input or constant");
        }),
        "graph output declared as input is rejected");
  expect_throw([&] { (void)compile_graph(output_is_input); },
               "compile rejects output/input tensor conflict");

  Graph output_is_constant = qgemm_graph();
  output_is_constant.tensors[1].flags |= TINY3TPU_TENSOR_OUTPUT;
  output_is_constant.outputs = {1};
  errors = validate(output_is_constant);
  check(std::any_of(errors.begin(), errors.end(), [](const std::string& error) {
          return contains(error, "output cannot also be input or constant");
        }),
        "graph output declared as constant is rejected");
  expect_throw([&] { (void)compile_graph(output_is_constant); },
               "compile rejects output/constant tensor conflict");

  Graph constant_activation = qgemm_graph();
  constant_activation.tensors[0].flags = TINY3TPU_TENSOR_CONSTANT;
  constant_activation.tensors[0].data = {3, -4};
  constant_activation.inputs.clear();
  errors = validate(constant_activation);
  check(std::any_of(errors.begin(), errors.end(), [](const std::string& error) {
          return contains(error, "QGEMM activation cannot be constant");
        }),
        "QGEMM constant activation is rejected by graph validation");
  expect_throw([&] { (void)compile_graph(constant_activation); },
               "compile rejects constant QGEMM activation");

  check_compiled_graph_validates(qgemm_graph(), "QGEMM");
}

void test_reshape_argmax_and_validation() {
  using namespace tiny3tpu;
  Graph graph;
  graph.tensors = {
      Tensor{0, "input", DType::I8, Layout::Packed, TINY3TPU_TENSOR_INPUT, {3}, 1.0f, 0, {}},
      Tensor{1, "reshaped", DType::I8, Layout::Packed, 0, {3}, 1.0f, 0, {}},
      Tensor{2, "index", DType::I32, Layout::Packed, TINY3TPU_TENSOR_OUTPUT, {1}, 1.0f, 0, {}},
  };
  graph.inputs = {0}; graph.outputs = {2};
  graph.operations = {
      Operation{Opcode::RESHAPE, {0}, {1}, ReshapeParams{{3}}},
      Operation{Opcode::ARGMAX, {1}, {2}, ArgmaxParams{0}},
  };
  const auto compiled = compile_graph(graph);
  ReferenceExecutor executor(compiled.graph); executor.set_input(0, {-2, 7, 1});
  check(executor.run(2) == std::vector<int32_t>({1}), "RESHAPE and ARGMAX reference execution");
  Graph invalid = graph;
  invalid.operations[1].opcode = static_cast<Opcode>(99);
  check(!validate(invalid).empty(), "unknown opcode rejected by graph validation");
  invalid = graph; invalid.operations[0].params = ReshapeParams{{2}};
  check(!validate(invalid).empty(), "bad reshape rejected by graph validation");

  const CompiledModel artifact = compile_graph(graph);
  const uint32_t operation_table = u32(artifact.bytes, TINY3TPU_HEADER_OPERATION_TABLE_OFFSET);
  const uint32_t reshape_record = operation_table;
  const uint32_t argmax_record = operation_table + TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
  const uint32_t reshape_params = u32(artifact.bytes, reshape_record + TINY3TPU_OPERATION_PARAMETER_OFFSET);
  const uint32_t argmax_params = u32(artifact.bytes, argmax_record + TINY3TPU_OPERATION_PARAMETER_OFFSET);
  const uint32_t tensor_table = u32(artifact.bytes, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET);
  const uint32_t reshaped_record = tensor_table + TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
  const uint32_t output_record = tensor_table + 2 * TINY3TPU_MODEL_TENSOR_RECORD_BYTES;
  std::string error;

  std::vector<uint8_t> malformed = artifact.bytes;
  put_u32(malformed, reshape_params, 0);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "RESHAPE rank"),
        "wire RESHAPE rank is validated");

  malformed = artifact.bytes;
  put_u32(malformed, reshape_params + 4, 2);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "RESHAPE descriptor"),
        "wire RESHAPE element count and shape are validated");

  malformed = artifact.bytes;
  put_u32(malformed, reshape_params + 20, 1);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "RESHAPE parameter reserved"),
        "wire RESHAPE reserved bytes are validated");

  malformed = artifact.bytes;
  put_u32(malformed, reshaped_record + TINY3TPU_TENSOR_SCALE_OFFSET, UINT32_C(0x40000000));
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "RESHAPE descriptor"),
        "wire RESHAPE quantization consistency is validated");

  malformed = artifact.bytes;
  put_u32(malformed, argmax_params, 1);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "ARGMAX axis"),
        "wire ARGMAX axis is validated");

  malformed = artifact.bytes;
  put_u32(malformed, argmax_params + 4, 1);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "ARGMAX parameter reserved"),
        "wire ARGMAX reserved bytes are validated");

  malformed = artifact.bytes;
  malformed[output_record + TINY3TPU_TENSOR_META_OFFSET] = TINY3TPU_DTYPE_I8;
  put_u32(malformed, output_record + TINY3TPU_TENSOR_BYTE_SIZE_OFFSET, 1);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "ARGMAX requires"),
        "wire ARGMAX output dtype is validated");

  malformed = artifact.bytes;
  malformed[output_record + TINY3TPU_TENSOR_META_OFFSET + 3] |= TINY3TPU_TENSOR_SCRATCH;
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "conflicting flags"),
        "scratch-flagged outputs are rejected");

  malformed = artifact.bytes;
  malformed[output_record + TINY3TPU_TENSOR_META_OFFSET + 3] &= ~TINY3TPU_TENSOR_OUTPUT;
  put_u32(malformed, TINY3TPU_HEADER_OUTPUT_COUNT_OFFSET, 0);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error) && contains(error, "no declared outputs"),
        "models without declared outputs are rejected");

  malformed = artifact.bytes;
  put_u32(malformed, reshape_record, TINY3TPU_OP_QCONV2D);
  refresh_crc(malformed);
  check(!validate_model_bytes(malformed, error), "unsupported wire operations are rejected");
}

void test_mnist_import(const std::string& path) {
  using namespace tiny3tpu;
  const CompiledModel model = compile_json_file(path);
  check(model.graph.inputs.size() == 1, "MNIST has one graph input");
  check(model.graph.outputs.size() == 1, "MNIST has one graph output");
  const Tensor& output = *std::find_if(model.graph.tensors.begin(), model.graph.tensors.end(), [&](const Tensor& t) { return t.id == model.graph.outputs.front(); });
  check(output.dtype == DType::I32, "MNIST terminal output preserves int32 logits");
  const auto& layer = model.graph.operations.back();
  const auto& input = *std::find_if(model.graph.tensors.begin(), model.graph.tensors.end(), [&](const Tensor& t) { return t.id == layer.inputs.front(); });
  const auto& weight = *std::find_if(model.graph.tensors.begin(), model.graph.tensors.end(), [&](const Tensor& t) { return t.id == layer.inputs[1]; });
  check(std::fabs(output.scale - input.scale * weight.scale) < 1e-5f, "terminal int32 output scale is preserved");
  std::string error; check(validate_model_bytes(model.bytes, error), "MNIST artifact validates: " + error);
  check(u32(model.bytes, TINY3TPU_HEADER_SCRATCH_OFFSET) == 0 &&
            u32(model.bytes, TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET) == 0,
        "MNIST artifact uses the v1 zero-scratch contract");
  std::vector<uint8_t> overlapping_scratch = model.bytes;
  put_u32(overlapping_scratch, TINY3TPU_HEADER_SCRATCH_OFFSET,
          u32(model.bytes, TINY3TPU_HEADER_ARENA_OFFSET));
  put_u32(overlapping_scratch, TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET, 16);
  refresh_crc(overlapping_scratch);
  check(!validate_model_bytes(overlapping_scratch, error),
        "nonzero scratch overlapping the activation arena is rejected");
  const std::filesystem::path malformed = std::filesystem::temp_directory_path() / "tiny3tpu-malformed.json";
  { std::ofstream file(malformed); file << R"({"layers":[{"w":[],"b":[],"scale_in":1,"scale_w":1,"scale_out":1}]})"; }
  expect_throw([&] { (void)compile_json_file(malformed.string()); }, "malformed JSON model rejected");
  std::filesystem::remove(malformed);
}
} // namespace

int main(int argc, char** argv) {
  try {
    test_abi_and_executor();
    test_qgemm_wire_semantics_and_constant_safety();
    test_graph_flag_contracts();
    test_reshape_argmax_and_validation();
    if (argc > 1) test_mnist_import(argv[1]);
  } catch (const std::exception& error) {
    std::cerr << "UNEXPECTED ERROR: " << error.what() << "\n";
    return 1;
  }
  if (failures != 0) return 1;
  std::cout << "all compiler tests passed\n";
  return 0;
}
