#ifndef TINY3TPU_COMPILER_HPP
#define TINY3TPU_COMPILER_HPP

#include "tiny3tpu_abi.h"
#include <cstdint>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace tiny3tpu {

enum class DType : uint8_t { I8 = TINY3TPU_DTYPE_I8, U8 = TINY3TPU_DTYPE_U8, I32 = TINY3TPU_DTYPE_I32 };
enum class Layout : uint8_t { Packed = TINY3TPU_LAYOUT_PACKED, NHWC = TINY3TPU_LAYOUT_NHWC, NCHW = TINY3TPU_LAYOUT_NCHW };
enum class Opcode : uint32_t { QGEMM = TINY3TPU_OP_QGEMM, QCONV2D = TINY3TPU_OP_QCONV2D, MAX_POOL_2D = TINY3TPU_OP_MAX_POOL_2D, RESHAPE = TINY3TPU_OP_RESHAPE, ARGMAX = TINY3TPU_OP_ARGMAX };

struct Tensor {
  uint32_t id = 0;
  std::string name;
  DType dtype = DType::I8;
  Layout layout = Layout::Packed;
  uint8_t flags = 0;
  std::vector<uint32_t> shape;
  float scale = 1.0f;
  int32_t zero_point = 0;
  std::vector<int32_t> data; // Constants use logical integer elements.
};

struct QGemmParams { int32_t multiplier = 0; uint32_t shift = 0; uint32_t flags = 0; };
struct QConv2DParams { uint32_t stride_h=1, stride_w=1, pad_top=0, pad_left=0, pad_bottom=0, pad_right=0, kernel_h=0, kernel_w=0, groups=1; int32_t multiplier=0; uint32_t shift=0, flags=0; };
struct MaxPool2DParams { uint32_t kernel_h=0, kernel_w=0, stride_h=1, stride_w=1, pad_top=0, pad_left=0, pad_bottom=0, pad_right=0; };
struct ReshapeParams { std::vector<uint32_t> shape; };
struct ArgmaxParams { uint32_t axis=0; };
using OpParams = std::variant<QGemmParams, QConv2DParams, MaxPool2DParams, ReshapeParams, ArgmaxParams>;

struct Operation { Opcode opcode; std::vector<uint32_t> inputs; std::vector<uint32_t> outputs; OpParams params; };
struct Graph { std::vector<Tensor> tensors; std::vector<Operation> operations; std::vector<uint32_t> inputs; std::vector<uint32_t> outputs; };
struct CompiledModel { Graph graph; std::vector<uint8_t> bytes; };

std::vector<std::string> validate(const Graph& graph);
CompiledModel compile_graph(Graph graph);
CompiledModel compile_json_file(const std::string& path);
Graph import_json_graph(const std::string& path);
bool validate_model_bytes(const std::vector<uint8_t>& bytes, std::string& error);

class ReferenceExecutor {
 public:
  explicit ReferenceExecutor(const Graph& graph);
  void set_input(uint32_t tensor_id, const std::vector<int32_t>& values);
  std::vector<int32_t> run(uint32_t output_id);
 private:
  const Graph& graph_;
  std::unordered_map<uint32_t, std::vector<int32_t>> values_;
};

} // namespace tiny3tpu

#endif
