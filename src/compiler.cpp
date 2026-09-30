#include "tiny3tpu_compiler.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <set>
#include <unordered_set>

namespace tiny3tpu {
namespace {

struct Json {
  using object = std::unordered_map<std::string, Json>;
  using array = std::vector<Json>;
  std::variant<std::nullptr_t, bool, double, std::string, array, object> value;

  bool has(const std::string& key) const {
    return std::holds_alternative<object>(value) &&
           std::get<object>(value).find(key) != std::get<object>(value).end();
  }
  const Json& at(const std::string& key) const { return std::get<object>(value).at(key); }
};

class JsonParser {
 public:
  explicit JsonParser(std::string text) : text_(std::move(text)) {}

  Json parse() {
    skip_space();
    Json result = parse_value();
    skip_space();
    if (position_ != text_.size()) fail("trailing characters");
    return result;
  }

 private:
  std::string text_;
  size_t position_ = 0;

  [[noreturn]] void fail(const std::string& message) const {
    throw std::runtime_error("JSON: " + message + " at byte " + std::to_string(position_));
  }
  void skip_space() {
    while (position_ < text_.size() &&
           std::isspace(static_cast<unsigned char>(text_[position_]))) ++position_;
  }
  bool consume(char expected) {
    skip_space();
    if (position_ < text_.size() && text_[position_] == expected) {
      ++position_;
      return true;
    }
    return false;
  }
  Json parse_value() {
    skip_space();
    if (position_ >= text_.size()) fail("unexpected end");
    switch (text_[position_]) {
      case '{': return parse_object();
      case '[': return parse_array();
      case '"': return Json{parse_string()};
      default: break;
    }
    if (text_.compare(position_, 4, "true") == 0) { position_ += 4; return Json{true}; }
    if (text_.compare(position_, 5, "false") == 0) { position_ += 5; return Json{false}; }
    if (text_.compare(position_, 4, "null") == 0) { position_ += 4; return Json{nullptr}; }
    const char* start = text_.c_str() + position_;
    char* end = nullptr;
    const double number = std::strtod(start, &end);
    if (end == start) fail("expected value");
    position_ += static_cast<size_t>(end - start);
    return Json{number};
  }
  Json parse_object() {
    consume('{');
    Json::object result;
    if (consume('}')) return Json{result};
    while (true) {
      skip_space();
      if (position_ >= text_.size() || text_[position_] != '"') fail("expected object key");
      std::string key = parse_string();
      if (!consume(':')) fail("expected colon");
      result.emplace(std::move(key), parse_value());
      if (consume('}')) return Json{result};
      if (!consume(',')) fail("expected comma");
    }
  }
  Json parse_array() {
    consume('[');
    Json::array result;
    if (consume(']')) return Json{result};
    while (true) {
      result.push_back(parse_value());
      if (consume(']')) return Json{result};
      if (!consume(',')) fail("expected comma");
    }
  }
  std::string parse_string() {
    if (position_ >= text_.size() || text_[position_] != '"') fail("expected string");
    ++position_;
    std::string result;
    while (position_ < text_.size()) {
      const char c = text_[position_++];
      if (c == '"') return result;
      if (c != '\\') { result.push_back(c); continue; }
      if (position_ >= text_.size()) fail("bad escape");
      const char escaped = text_[position_++];
      if (escaped == 'n') result.push_back('\n');
      else if (escaped == 'r') result.push_back('\r');
      else if (escaped == 't') result.push_back('\t');
      else if (escaped == '"' || escaped == '\\' || escaped == '/') result.push_back(escaped);
      else fail("unsupported escape");
    }
    fail("unterminated string");
  }
};

Json read_json(const std::string& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open " + path);
  std::ostringstream contents;
  contents << input.rdbuf();
  return JsonParser(contents.str()).parse();
}

const Json::array& array_at(const Json& object, const std::string& key) {
  return std::get<Json::array>(object.at(key).value);
}
std::string string_at(const Json& object, const std::string& key) {
  return std::get<std::string>(object.at(key).value);
}
double number_at(const Json& object, const std::string& key) {
  return std::get<double>(object.at(key).value);
}
bool bool_at(const Json& object, const std::string& key) {
  return std::get<bool>(object.at(key).value);
}
uint32_t u32_at(const Json& object, const std::string& key) {
  const double value = number_at(object, key);
  if (!std::isfinite(value) || value < 0.0 || value > UINT32_MAX || std::floor(value) != value)
    throw std::runtime_error(key + ": expected uint32");
  return static_cast<uint32_t>(value);
}
int32_t i32_at(const Json& object, const std::string& key) {
  const double value = number_at(object, key);
  if (!std::isfinite(value) || value < std::numeric_limits<int32_t>::min() ||
      value > std::numeric_limits<int32_t>::max() || std::floor(value) != value)
    throw std::runtime_error(key + ": expected int32");
  return static_cast<int32_t>(value);
}
float f32_at(const Json& object, const std::string& key) {
  const double value = number_at(object, key);
  if (!std::isfinite(value) || value <= 0.0 || value > std::numeric_limits<float>::max())
    throw std::runtime_error(key + ": expected positive finite scale");
  return static_cast<float>(value);
}
std::vector<uint32_t> shape_at(const Json& object, const std::string& key) {
  std::vector<uint32_t> shape;
  for (const Json& dimension : array_at(object, key)) {
    const double value = std::get<double>(dimension.value);
    if (!std::isfinite(value) || value <= 0.0 || value > UINT32_MAX || std::floor(value) != value)
      throw std::runtime_error(key + ": dimensions must be positive uint32 values");
    shape.push_back(static_cast<uint32_t>(value));
  }
  return shape;
}
uint32_t element_count(const std::vector<uint32_t>& shape) {
  uint64_t count = 1;
  for (uint32_t dimension : shape) {
    count *= dimension;
    if (count > UINT32_MAX) throw std::runtime_error("tensor element count overflow");
  }
  return static_cast<uint32_t>(count);
}
bool try_element_count(const std::vector<uint32_t>& shape, uint32_t& result) {
  uint64_t count = 1;
  if (shape.empty()) return false;
  for (uint32_t dimension : shape) {
    if (dimension == 0 || count > UINT32_MAX / dimension) return false;
    count *= dimension;
  }
  result = static_cast<uint32_t>(count);
  return true;
}
uint32_t checked_add(uint32_t a, uint32_t b, const char* what) {
  if (b > UINT32_MAX - a) throw std::runtime_error(std::string(what) + " overflows uint32");
  return a + b;
}
uint32_t checked_mul(uint32_t a, uint32_t b, const char* what) {
  if (a != 0 && b > UINT32_MAX / a) throw std::runtime_error(std::string(what) + " overflows uint32");
  return a * b;
}
uint32_t align_up(uint32_t value, uint32_t alignment) {
  const uint32_t remainder = value % alignment;
  return remainder == 0 ? value : checked_add(value, alignment - remainder, "alignment");
}
uint32_t scalar_bits(float value) { uint32_t bits; std::memcpy(&bits, &value, sizeof(bits)); return bits; }
float bits_scalar(uint32_t bits) { float value; std::memcpy(&value, &bits, sizeof(value)); return value; }

bool scales_equal(float lhs, float rhs) {
  const double a = lhs;
  const double b = rhs;
  return std::fabs(a - b) <= 1e-5 * std::max({std::fabs(a), std::fabs(b), 1e-30});
}

struct FixedPointMultiplier {
  int32_t multiplier = 0;
  uint32_t shift = 0;
};

FixedPointMultiplier choose_multiplier(double real_multiplier) {
  if (!std::isfinite(real_multiplier) || real_multiplier <= 0.0)
    throw std::runtime_error("requantization multiplier must be positive and finite");
  for (int shift = 62; shift >= 0; --shift) {
    const long double scaled = std::ldexp(static_cast<long double>(real_multiplier), shift);
    const long double rounded = std::floor(scaled + 0.5L);
    if (rounded >= 1.0L && rounded <= std::numeric_limits<int32_t>::max())
      return {static_cast<int32_t>(rounded), static_cast<uint32_t>(shift)};
  }
  throw std::runtime_error("requantization multiplier is not representable");
}

bool multiplier_matches(double real_multiplier, int32_t multiplier, uint32_t shift) {
  if (!std::isfinite(real_multiplier) || real_multiplier <= 0.0 || shift > 62 || multiplier <= 0)
    return false;
  const long double rounded = std::floor(std::ldexp(static_cast<long double>(real_multiplier), shift) + 0.5L);
  return rounded >= 1.0L && rounded <= std::numeric_limits<int32_t>::max() &&
         static_cast<int64_t>(rounded) == multiplier;
}

bool spatial_output_dimension(uint32_t input, uint32_t pad_before,
                             uint32_t pad_after, uint32_t kernel,
                             uint32_t stride, uint32_t& output) {
  const uint64_t padded = static_cast<uint64_t>(input) + pad_before + pad_after;
  if (kernel == 0 || stride == 0 || padded < kernel) return false;
  const uint64_t result = (padded - kernel) / stride + 1;
  if (result > UINT32_MAX) return false;
  output = static_cast<uint32_t>(result);
  return true;
}

bool checked_scale_product(float lhs, float rhs, float& product) {
  const double value = static_cast<double>(lhs) * static_cast<double>(rhs);
  if (!std::isfinite(value) || value <= 0.0 ||
      value > static_cast<double>(std::numeric_limits<float>::max()))
    return false;
  product = static_cast<float>(value);
  return std::isfinite(product) && product > 0.0f;
}

bool conservative_image_accumulator_bound(const Tensor& activation,
                                          const Tensor& weight,
                                          const Tensor& bias) {
  if (weight.shape.size() != 4 || bias.shape.size() != 1 ||
      weight.shape[3] != bias.shape[0])
    return false;
  uint32_t weight_elements = 0;
  uint32_t bias_elements = 0;
  if (!try_element_count(weight.shape, weight_elements) ||
      !try_element_count(bias.shape, bias_elements) ||
      weight.data.size() != weight_elements || bias.data.size() != bias_elements)
    return false;

  const uint64_t input_abs = activation.dtype == DType::U8 ? 255U : 128U;
  const uint32_t kernel_h = weight.shape[0];
  const uint32_t kernel_w = weight.shape[1];
  const uint32_t input_channels = weight.shape[2];
  const uint32_t output_channels = weight.shape[3];
  for (uint32_t output = 0; output < output_channels; ++output) {
    uint64_t worst = 0;
    for (uint32_t kh = 0; kh < kernel_h; ++kh) {
      for (uint32_t kw = 0; kw < kernel_w; ++kw) {
        for (uint32_t input = 0; input < input_channels; ++input) {
          const size_t position =
              ((static_cast<size_t>(kh) * kernel_w + kw) * input_channels + input) *
                  output_channels + output;
          const int32_t value = weight.data[position];
          const uint64_t magnitude =
              value < 0 ? uint64_t(-(int64_t)value) : uint64_t(value);
          if (magnitude > (UINT64_MAX - worst) / input_abs) return false;
          worst += magnitude * input_abs;
        }
      }
    }
    const int32_t bias_value = bias.data[output];
    const uint64_t bias_magnitude =
        bias_value < 0 ? uint64_t(-(int64_t)bias_value) : uint64_t(bias_value);
    if (bias_magnitude > UINT64_MAX - worst ||
        worst + bias_magnitude > static_cast<uint64_t>(INT32_MAX))
      return false;
  }
  return true;
}

bool conservative_accumulator_bound(const Tensor& activation, const Tensor& weight, const Tensor& bias) {
  if (weight.shape.size() != 2 || bias.shape.size() != 1 || weight.shape[0] != bias.shape[0]) return false;
  uint32_t weight_elements = 0;
  uint32_t bias_elements = 0;
  if (!try_element_count(weight.shape, weight_elements) ||
      !try_element_count(bias.shape, bias_elements) ||
      weight.data.size() != weight_elements || bias.data.size() != bias_elements)
    return false;
  const uint64_t input_abs = activation.dtype == DType::U8 ? 255U : 128U;
  const uint32_t output_count = weight.shape[0];
  const uint32_t input_count = weight.shape[1];
  for (uint32_t output = 0; output < output_count; ++output) {
    uint64_t worst = 0;
    for (uint32_t input = 0; input < input_count; ++input) {
      const int32_t value = weight.data[static_cast<size_t>(output) * input_count + input];
      const uint64_t magnitude = value < 0 ? uint64_t(-(int64_t)value) : uint64_t(value);
      if (magnitude > (UINT64_MAX - worst) / input_abs) return false;
      worst += magnitude * input_abs;
    }
    const int32_t bias_value = bias.data[output];
    const uint64_t bias_magnitude = bias_value < 0 ? uint64_t(-(int64_t)bias_value) : uint64_t(bias_value);
    if (bias_magnitude > UINT64_MAX - worst) return false;
    if (worst + bias_magnitude > static_cast<uint64_t>(std::numeric_limits<int32_t>::max())) return false;
  }
  return true;
}

Tensor& find_tensor(Graph& graph, uint32_t id) {
  for (Tensor& tensor : graph.tensors) if (tensor.id == id) return tensor;
  throw std::runtime_error("unknown tensor id " + std::to_string(id));
}
const Tensor& find_tensor(const Graph& graph, uint32_t id) {
  for (const Tensor& tensor : graph.tensors) if (tensor.id == id) return tensor;
  throw std::runtime_error("unknown tensor id " + std::to_string(id));
}
Opcode opcode_from_string(const std::string& value) {
  if (value == "qgemm" || value == "QGEMM") return Opcode::QGEMM;
  if (value == "qconv2d" || value == "QCONV2D") return Opcode::QCONV2D;
  if (value == "max_pool_2d" || value == "MAX_POOL_2D") return Opcode::MAX_POOL_2D;
  if (value == "reshape" || value == "RESHAPE") return Opcode::RESHAPE;
  if (value == "argmax" || value == "ARGMAX") return Opcode::ARGMAX;
  throw std::runtime_error("unsupported opcode '" + value + "'");
}
void add_flat_data(Tensor& tensor, const Json& values, const std::string& where) {
  for (const Json& value : std::get<Json::array>(values.value)) {
    const double number = std::get<double>(value.value);
    if (!std::isfinite(number) || std::floor(number) != number ||
        number < std::numeric_limits<int32_t>::min() || number > std::numeric_limits<int32_t>::max())
      throw std::runtime_error(where + ": data must contain int32 values");
    tensor.data.push_back(static_cast<int32_t>(number));
  }
}

Graph import_graph_value(const Json& root) {
  Graph graph;
  if (root.has("layers")) {
    const auto& layers = array_at(root, "layers");
    if (layers.empty()) throw std::runtime_error("layers must contain at least one layer");
    uint32_t next_id = 0;
    uint32_t previous = 0;
    bool first = true;
    float previous_scale = 0.0f;
    int32_t previous_zp = 0;
    for (size_t layer_index = 0; layer_index < layers.size(); ++layer_index) {
      const Json& layer = layers[layer_index];
      const auto& rows = array_at(layer, "w");
      const auto& biases = array_at(layer, "b");
      if (rows.empty()) throw std::runtime_error("layer" + std::to_string(layer_index) + ": empty weights");
      if (!std::holds_alternative<Json::array>(rows.front().value) || std::get<Json::array>(rows.front().value).empty())
        throw std::runtime_error("layer" + std::to_string(layer_index) + ": empty weight row");
      const uint32_t out_dim = static_cast<uint32_t>(rows.size());
      const uint32_t in_dim = static_cast<uint32_t>(std::get<Json::array>(rows.front().value).size());
      if (in_dim == 0) throw std::runtime_error("layer" + std::to_string(layer_index) + ": zero input dimension");
      const float scale_in = f32_at(layer, "scale_in");
      const float scale_w = f32_at(layer, "scale_w");
      const float scale_out = f32_at(layer, "scale_out");
      const int32_t zp_in = layer.has("zp_in") ? i32_at(layer, "zp_in") : 0;
      const int32_t zp_w = layer.has("zp_w") ? i32_at(layer, "zp_w") : 0;
      const int32_t zp_out = layer.has("zp_out") ? i32_at(layer, "zp_out") : 0;
      if (zp_in != 0 || zp_w != 0 || zp_out != 0) throw std::runtime_error("layer" + std::to_string(layer_index) + ": only zero-point 0 is supported");
      if (!first && (std::fabs(scale_in - previous_scale) > 1e-6f * std::max(1.0f, std::fabs(previous_scale)) || zp_in != previous_zp))
        throw std::runtime_error("layer" + std::to_string(layer_index) + ": input quantization does not match previous output");
      if (root.has("input_scale") && first && std::fabs(scale_in - f32_at(root, "input_scale")) > 1e-6f * std::max(1.0f, scale_in))
        throw std::runtime_error("input_scale does not match layer0 scale_in");
      if (first) {
        graph.tensors.push_back(Tensor{next_id++, "input", DType::I8, Layout::Packed, TINY3TPU_TENSOR_INPUT,
                                       {in_dim}, scale_in, 0, {}});
        graph.inputs.push_back(graph.tensors.back().id);
        previous = graph.tensors.back().id;
        first = false;
      } else if (find_tensor(graph, previous).shape.back() != in_dim) {
        throw std::runtime_error("layer" + std::to_string(layer_index) + ": adjacent dimensions do not match");
      }
      Tensor weight{next_id++, "layer" + std::to_string(layer_index) + "_weight", DType::I8, Layout::Packed,
                    TINY3TPU_TENSOR_CONSTANT, {out_dim, in_dim}, scale_w, 0, {}};
      for (size_t row_index = 0; row_index < rows.size(); ++row_index) {
        const auto& row = std::get<Json::array>(rows[row_index].value);
        if (row.size() != in_dim) throw std::runtime_error("layer" + std::to_string(layer_index) + ": ragged weights");
        for (const Json& value : row) {
          const int32_t q = i32_at(Json{Json::object{{"value", value}}}, "value");
          if (q < -128 || q > 127) throw std::runtime_error("layer" + std::to_string(layer_index) + ": weight outside int8");
          weight.data.push_back(q);
        }
      }
      graph.tensors.push_back(std::move(weight));
      Tensor bias{next_id++, "layer" + std::to_string(layer_index) + "_bias", DType::I32, Layout::Packed,
                  TINY3TPU_TENSOR_CONSTANT, {out_dim}, scale_in * scale_w, 0, {}};
      if (biases.size() != out_dim) throw std::runtime_error("layer" + std::to_string(layer_index) + ": bias length mismatch");
      for (const Json& value : biases) {
        const double number = std::get<double>(value.value);
        if (!std::isfinite(number) || std::floor(number) != number || number < std::numeric_limits<int32_t>::min() || number > std::numeric_limits<int32_t>::max())
          throw std::runtime_error("layer" + std::to_string(layer_index) + ": bias outside int32");
        bias.data.push_back(static_cast<int32_t>(number));
      }
      graph.tensors.push_back(std::move(bias));
      const bool last = layer_index + 1 == layers.size();
      const bool requantize = last ? (layer.has("output_requant") && bool_at(layer, "output_requant")) : true;
      const std::string activation = layer.has("activation") ? string_at(layer, "activation") : (last ? "none" : "relu");
      if (activation != "none" && activation != "linear" && activation != "identity" && activation != "relu")
        throw std::runtime_error("layer" + std::to_string(layer_index) + ": unsupported activation " + activation);
      if (activation == "relu" && !requantize) throw std::runtime_error("layer" + std::to_string(layer_index) + ": ReLU requires int8 output");
      uint32_t flags = requantize ? TINY3TPU_QGEMM_FLAG_REQUANT : 0;
      if (activation == "relu") flags |= TINY3TPU_QGEMM_FLAG_RELU;
      int32_t multiplier = 0;
      uint32_t shift = 0;
      if (requantize) {
        const double real_multiplier = static_cast<double>(scale_in) * scale_w / scale_out;
        const FixedPointMultiplier fixed = choose_multiplier(real_multiplier);
        multiplier = fixed.multiplier;
        shift = fixed.shift;
      }
      const float output_scale = requantize ? scale_out : scale_in * scale_w;
      Tensor output{next_id++, "layer" + std::to_string(layer_index) + "_output", requantize ? DType::I8 : DType::I32,
                    Layout::Packed, static_cast<uint8_t>(last ? TINY3TPU_TENSOR_OUTPUT : 0), {out_dim}, output_scale, 0, {}};
      const uint32_t output_id = output.id;
      graph.tensors.push_back(std::move(output));
      const uint32_t weight_id = graph.tensors[graph.tensors.size() - 3].id;
      const uint32_t bias_id = graph.tensors[graph.tensors.size() - 2].id;
      graph.operations.push_back(Operation{Opcode::QGEMM, {previous, weight_id, bias_id}, {output_id}, QGemmParams{multiplier, shift, flags}});
      previous = output_id;
      previous_scale = output_scale;
      previous_zp = 0;
    }
    graph.outputs = {previous};
    return graph;
  }

  const auto& tensors = array_at(root, "tensors");
  for (size_t i = 0; i < tensors.size(); ++i) {
    const Json& input = tensors[i];
    Tensor tensor;
    tensor.id = input.has("id") ? u32_at(input, "id") : static_cast<uint32_t>(i);
    tensor.name = input.has("name") ? string_at(input, "name") : "tensor" + std::to_string(tensor.id);
    const std::string dtype = input.has("dtype") ? string_at(input, "dtype") : "i8";
    if (dtype == "i8") tensor.dtype = DType::I8;
    else if (dtype == "u8") tensor.dtype = DType::U8;
    else if (dtype == "i32") tensor.dtype = DType::I32;
    else throw std::runtime_error("tensor " + std::to_string(tensor.id) + ": unsupported dtype " + dtype);
    const std::string layout = input.has("layout") ? string_at(input, "layout") : "packed";
    if (layout == "NHWC") tensor.layout = Layout::NHWC;
    else if (layout == "NCHW") tensor.layout = Layout::NCHW;
    else if (layout == "packed") tensor.layout = Layout::Packed;
    else throw std::runtime_error("tensor " + std::to_string(tensor.id) + ": unknown layout " + layout);
    tensor.shape = shape_at(input, "shape");
    tensor.scale = input.has("scale") ? f32_at(input, "scale") : 1.0f;
    tensor.zero_point = input.has("zero_point") ? i32_at(input, "zero_point") : 0;
    if (input.has("flags")) {
      const Json& flags = input.at("flags");
      if (std::holds_alternative<double>(flags.value)) tensor.flags = static_cast<uint8_t>(u32_at(input, "flags"));
      else for (const Json& flag : std::get<Json::array>(flags.value)) {
        const std::string name = std::get<std::string>(flag.value);
        if (name == "input") tensor.flags |= TINY3TPU_TENSOR_INPUT;
        else if (name == "output") tensor.flags |= TINY3TPU_TENSOR_OUTPUT;
        else if (name == "constant") tensor.flags |= TINY3TPU_TENSOR_CONSTANT;
        else if (name == "scratch") tensor.flags |= TINY3TPU_TENSOR_SCRATCH;
        else throw std::runtime_error("unknown tensor flag " + name);
      }
    }
    if (input.has("data")) add_flat_data(tensor, input.at("data"), "tensor.data");
    graph.tensors.push_back(std::move(tensor));
  }
  for (const Json& input : array_at(root, "inputs")) graph.inputs.push_back(u32_at(Json{Json::object{{"value", input}}}, "value"));
  for (const Json& output : array_at(root, "outputs")) graph.outputs.push_back(u32_at(Json{Json::object{{"value", output}}}, "value"));
  for (const Json& object : array_at(root, "operations")) {
    const Json& opcode_value = object.at("opcode");
    const Opcode opcode = std::holds_alternative<double>(opcode_value.value)
                              ? static_cast<Opcode>(u32_at(Json{Json::object{{"value", opcode_value}}}, "value"))
                              : opcode_from_string(std::get<std::string>(opcode_value.value));
    Operation operation{opcode, {}, {}, ArgmaxParams{}};
    for (const Json& input : array_at(object, "inputs")) operation.inputs.push_back(u32_at(Json{Json::object{{"value", input}}}, "value"));
    for (const Json& output : array_at(object, "outputs")) operation.outputs.push_back(u32_at(Json{Json::object{{"value", output}}}, "value"));
    const Json empty_params{Json::object{}};
    const Json& params = object.has("params") ? object.at("params") : empty_params;
    auto optional_u32 = [&](const std::string& key, uint32_t fallback) { return params.has(key) ? u32_at(params, key) : fallback; };
    if (opcode == Opcode::QGEMM) {
      uint32_t flags = optional_u32("flags", 0);
      if (params.has("requantize") && bool_at(params, "requantize")) flags |= TINY3TPU_QGEMM_FLAG_REQUANT;
      if (params.has("relu") && bool_at(params, "relu")) flags |= TINY3TPU_QGEMM_FLAG_RELU;
      operation.params = QGemmParams{params.has("multiplier") ? i32_at(params, "multiplier") : 0, optional_u32("shift", 0), flags};
    } else if (opcode == Opcode::QCONV2D) {
      operation.params = QConv2DParams{optional_u32("stride_h", 1), optional_u32("stride_w", 1), optional_u32("pad_top", 0), optional_u32("pad_left", 0), optional_u32("pad_bottom", 0), optional_u32("pad_right", 0), optional_u32("kernel_h", 0), optional_u32("kernel_w", 0), optional_u32("groups", 1), params.has("multiplier") ? i32_at(params, "multiplier") : 0, optional_u32("shift", 0), optional_u32("flags", 0)};
    } else if (opcode == Opcode::MAX_POOL_2D) {
      operation.params = MaxPool2DParams{optional_u32("kernel_h", 0), optional_u32("kernel_w", 0), optional_u32("stride_h", 1), optional_u32("stride_w", 1), optional_u32("pad_top", 0), optional_u32("pad_left", 0), optional_u32("pad_bottom", 0), optional_u32("pad_right", 0)};
    } else if (opcode == Opcode::RESHAPE) {
      operation.params = ReshapeParams{shape_at(params, "shape")};
    } else {
      operation.params = ArgmaxParams{optional_u32("axis", 0)};
    }
    graph.operations.push_back(std::move(operation));
  }
  return graph;
}

struct Writer {
  std::vector<uint8_t> bytes;
  void u8(uint8_t value) { bytes.push_back(value); }
  void u16(uint16_t value) { u8(static_cast<uint8_t>(value)); u8(static_cast<uint8_t>(value >> 8)); }
  void u32(uint32_t value) { for (unsigned i = 0; i < 4; ++i) u8(static_cast<uint8_t>(value >> (8 * i))); }
  void i32(int32_t value) { u32(static_cast<uint32_t>(value)); }
  void zero(size_t count) { bytes.insert(bytes.end(), count, 0); }
  void align(uint32_t alignment) { while (bytes.size() % alignment != 0) u8(0); }
};
uint32_t read_u32(const std::vector<uint8_t>& bytes, size_t offset) {
  return uint32_t(bytes[offset]) | (uint32_t(bytes[offset + 1]) << 8) | (uint32_t(bytes[offset + 2]) << 16) | (uint32_t(bytes[offset + 3]) << 24);
}
// The model header carries one canonical uint32 version field on the wire.
void write_u32(std::vector<uint8_t>& bytes, size_t offset, uint32_t value) { for (unsigned i = 0; i < 4; ++i) bytes[offset + i] = static_cast<uint8_t>(value >> (8 * i)); }
uint32_t crc32(const std::vector<uint8_t>& bytes) {
  uint32_t crc = 0xffffffffU;
  for (uint8_t byte : bytes) { crc ^= byte; for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U))); }
  return ~crc;
}
uint32_t dtype_bytes(DType type) { return type == DType::I32 ? 4U : 1U; }
void write_tensor_record(Writer& writer, const Tensor& tensor, uint32_t offset, uint32_t size) {
  writer.u32(tensor.id); writer.u8(static_cast<uint8_t>(tensor.dtype)); writer.u8(static_cast<uint8_t>(tensor.shape.size())); writer.u8(static_cast<uint8_t>(tensor.layout)); writer.u8(tensor.flags);
  for (unsigned i = 0; i < 4; ++i) writer.u32(i < tensor.shape.size() ? tensor.shape[i] : 0);
  writer.u32(offset); writer.u32(size); writer.u32(scalar_bits(tensor.scale)); writer.i32(tensor.zero_point); writer.u32(0); writer.u32(0);
}

} // namespace

std::vector<std::string> validate(const Graph& graph) {
  std::vector<std::string> errors;
  if (graph.tensors.empty()) errors.emplace_back("graph has no tensors");
  if (graph.operations.empty()) errors.emplace_back("graph has no operations");
  if (graph.inputs.empty()) errors.emplace_back("graph has no inputs");
  if (graph.outputs.empty()) errors.emplace_back("graph has no outputs");
  std::unordered_map<uint32_t, size_t> ids;
  for (const Tensor& tensor : graph.tensors) {
    if (tensor.id == UINT32_MAX) errors.emplace_back("tensor id is reserved for absent operands");
    if (!ids.emplace(tensor.id, ids.size()).second) errors.push_back("duplicate tensor id " + std::to_string(tensor.id));
    if (tensor.shape.empty() || tensor.shape.size() > TINY3TPU_MAX_RANK) errors.push_back("tensor " + std::to_string(tensor.id) + ": rank must be 1..4");
    uint32_t count = 0;
    if (try_element_count(tensor.shape, count)) {
      if (tensor.dtype == DType::I32 && count > UINT32_MAX / 4U)
        errors.emplace_back("tensor byte size exceeds uint32 ABI limit");
      if (tensor.flags & TINY3TPU_TENSOR_CONSTANT) {
        if (tensor.data.size() != count) errors.push_back("tensor " + std::to_string(tensor.id) + ": constant data size mismatch");
      } else if (!tensor.data.empty()) errors.push_back("tensor " + std::to_string(tensor.id) + ": nonconstant tensor has data");
    } else errors.push_back("tensor " + std::to_string(tensor.id) + ": dimensions must be nonzero and fit in uint32 element count");
    if (tensor.flags & ~uint8_t(TINY3TPU_TENSOR_INPUT | TINY3TPU_TENSOR_OUTPUT |
                                TINY3TPU_TENSOR_CONSTANT | TINY3TPU_TENSOR_SCRATCH))
      errors.push_back("tensor " + std::to_string(tensor.id) + ": unknown tensor flags");
    if (!std::isfinite(tensor.scale) || tensor.scale <= 0.0f) errors.push_back("tensor " + std::to_string(tensor.id) + ": invalid scale");
    if (tensor.zero_point != 0) errors.push_back("tensor " + std::to_string(tensor.id) + ": only zero-point 0 is supported");
    if ((tensor.flags & TINY3TPU_TENSOR_CONSTANT) && (tensor.flags & TINY3TPU_TENSOR_INPUT)) errors.push_back("tensor " + std::to_string(tensor.id) + ": cannot be input and constant");
    if (tensor.flags & TINY3TPU_TENSOR_SCRATCH) errors.push_back("tensor " + std::to_string(tensor.id) + ": scratch tensors are unsupported in this host slice");
    if (static_cast<uint8_t>(tensor.dtype) < static_cast<uint8_t>(DType::I8) ||
        static_cast<uint8_t>(tensor.dtype) > static_cast<uint8_t>(DType::I32))
      errors.push_back("tensor " + std::to_string(tensor.id) + ": unknown dtype");
    if (static_cast<uint8_t>(tensor.layout) > static_cast<uint8_t>(Layout::NCHW))
      errors.push_back("tensor " + std::to_string(tensor.id) + ": unknown layout");
    if (tensor.dtype == DType::I8 || tensor.dtype == DType::U8) for (int32_t value : tensor.data) if ((tensor.dtype == DType::I8 && (value < -128 || value > 127)) || (tensor.dtype == DType::U8 && (value < 0 || value > 255))) errors.push_back("tensor " + std::to_string(tensor.id) + ": data outside dtype range");
  }
  auto known = [&](uint32_t id) { return ids.find(id) != ids.end(); };
  auto tensor_for = [&](uint32_t id) -> const Tensor* {
    const auto it = ids.find(id);
    return it == ids.end() ? nullptr : &graph.tensors[it->second];
  };
  std::unordered_set<uint32_t> inputs(graph.inputs.begin(), graph.inputs.end());
  std::unordered_set<uint32_t> outputs(graph.outputs.begin(), graph.outputs.end());
  if (inputs.size() != graph.inputs.size() || outputs.size() != graph.outputs.size()) errors.emplace_back("duplicate graph input/output id");
  if (!std::is_sorted(graph.inputs.begin(), graph.inputs.end()) || !std::is_sorted(graph.outputs.begin(), graph.outputs.end())) errors.emplace_back("graph input/output IDs must be in ascending canonical order");
  for (uint32_t id : graph.inputs) if (!known(id) || !(tensor_for(id)->flags & TINY3TPU_TENSOR_INPUT)) errors.push_back("graph input is not a flagged tensor: " + std::to_string(id));
  for (uint32_t id : graph.outputs) if (!known(id) || !(tensor_for(id)->flags & TINY3TPU_TENSOR_OUTPUT)) errors.push_back("graph output is not a flagged tensor: " + std::to_string(id));
  for (const Tensor& tensor : graph.tensors) {
    const bool flagged_input = (tensor.flags & TINY3TPU_TENSOR_INPUT) != 0;
    const bool flagged_output = (tensor.flags & TINY3TPU_TENSOR_OUTPUT) != 0;
    if (flagged_input != (inputs.count(tensor.id) != 0)) errors.push_back("tensor " + std::to_string(tensor.id) + ": input flag/list mismatch");
    if (flagged_output != (outputs.count(tensor.id) != 0)) errors.push_back("tensor " + std::to_string(tensor.id) + ": output flag/list mismatch");
    if (flagged_output && (flagged_input || (tensor.flags & TINY3TPU_TENSOR_CONSTANT)))
      errors.push_back("tensor " + std::to_string(tensor.id) + ": output cannot also be input or constant");
  }
  std::unordered_set<uint32_t> produced;
  for (uint32_t id : graph.inputs) produced.insert(id);
  for (const Tensor& tensor : graph.tensors) if (tensor.flags & TINY3TPU_TENSOR_CONSTANT) produced.insert(tensor.id);
  for (size_t index = 0; index < graph.operations.size(); ++index) {
    const Operation& operation = graph.operations[index];
    const auto require_arity = [&](size_t in, size_t out) { if (operation.inputs.size() != in || operation.outputs.size() != out) errors.push_back("op " + std::to_string(index) + ": invalid operand count"); };
    for (uint32_t id : operation.inputs) { if (!known(id)) errors.push_back("op " + std::to_string(index) + ": unknown input tensor"); else if (!produced.count(id)) errors.push_back("op " + std::to_string(index) + ": input is not available before operation"); }
    for (uint32_t id : operation.outputs) { if (!known(id)) errors.push_back("op " + std::to_string(index) + ": unknown output tensor"); else if (produced.count(id)) errors.push_back("op " + std::to_string(index) + ": output tensor already produced"); }
    bool all_references_known = true;
    for (uint32_t id : operation.inputs) if (!known(id)) all_references_known = false;
    for (uint32_t id : operation.outputs) if (!known(id)) all_references_known = false;
    if (!all_references_known) continue;
    switch (operation.opcode) {
      case Opcode::QGEMM: {
        require_arity(3, 1); if (operation.inputs.size() != 3 || operation.outputs.size() != 1) break;
        if (!std::holds_alternative<QGemmParams>(operation.params)) { errors.push_back("op " + std::to_string(index) + ": malformed QGEMM params"); break; }
        const Tensor& a=find_tensor(graph,operation.inputs[0]); const Tensor& w=find_tensor(graph,operation.inputs[1]); const Tensor& b=find_tensor(graph,operation.inputs[2]); const Tensor& out=find_tensor(graph,operation.outputs[0]); const QGemmParams p=std::get<QGemmParams>(operation.params);
        if (a.dtype != DType::I8 && a.dtype != DType::U8) errors.push_back("op " + std::to_string(index) + ": QGEMM activation must be int8/uint8");
        if (a.flags & TINY3TPU_TENSOR_CONSTANT) errors.push_back("op " + std::to_string(index) + ": QGEMM activation cannot be constant");
        if (w.dtype != DType::I8 || !(w.flags & TINY3TPU_TENSOR_CONSTANT) || w.shape.size()!=2) errors.push_back("op " + std::to_string(index) + ": QGEMM weight must be constant rank-2 int8");
        if (b.dtype != DType::I32 || !(b.flags & TINY3TPU_TENSOR_CONSTANT) || b.shape.size()!=1) errors.push_back("op " + std::to_string(index) + ": QGEMM bias must be constant rank-1 int32");
        if (a.shape.size()<1 || a.shape.size()>2 || w.shape.size()!=2 || b.shape.size()!=1 || out.shape.size()<1 || out.shape.size()>2) errors.push_back("op " + std::to_string(index) + ": unsupported QGEMM rank");
        else { const uint32_t k=w.shape[1], n=w.shape[0], m=a.shape.size()==1?1:a.shape[0]; if (a.shape.back()!=k || b.shape[0]!=n || (out.shape.size()==1 ? (m!=1||out.shape[0]!=n) : (out.shape[0]!=m||out.shape[1]!=n))) errors.push_back("op " + std::to_string(index) + ": QGEMM shapes do not match"); }
        if (a.layout != Layout::Packed || w.layout != Layout::Packed || b.layout != Layout::Packed || out.layout != Layout::Packed) errors.push_back("op " + std::to_string(index) + ": QGEMM requires packed tensors");
        if (p.shift > 62 || (p.flags & ~(TINY3TPU_QGEMM_FLAG_REQUANT|TINY3TPU_QGEMM_FLAG_RELU|TINY3TPU_QGEMM_FLAG_WEIGHT_OUT_IN))) errors.push_back("op " + std::to_string(index) + ": invalid QGEMM shift or flags");
        if ((p.flags & TINY3TPU_QGEMM_FLAG_REQUANT) && out.dtype != DType::I8) errors.push_back("op " + std::to_string(index) + ": requantized QGEMM output must be int8");
        if ((p.flags & TINY3TPU_QGEMM_FLAG_RELU) && out.dtype != DType::I8) errors.push_back("op " + std::to_string(index) + ": ReLU on int32 output is unsupported");
        if (!scales_equal(b.scale, a.scale * w.scale)) errors.push_back("op " + std::to_string(index) + ": bias scale must equal input scale times weight scale");
        uint32_t weight_elements = 0;
        uint32_t bias_elements = 0;
        const bool valid_constant_shapes_and_data =
            w.shape.size() == 2 && b.shape.size() == 1 &&
            try_element_count(w.shape, weight_elements) &&
            try_element_count(b.shape, bias_elements) &&
            w.data.size() == weight_elements && b.data.size() == bias_elements;
        if (valid_constant_shapes_and_data && !conservative_accumulator_bound(a, w, b))
          errors.push_back("op " + std::to_string(index) + ": int32 accumulation may overflow");
        if (p.flags & TINY3TPU_QGEMM_FLAG_REQUANT) {
          if (!multiplier_matches(static_cast<double>(a.scale) * w.scale / out.scale, p.multiplier, p.shift)) errors.push_back("op " + std::to_string(index) + ": multiplier is inconsistent with tensor scales");
        } else if (out.dtype != DType::I32 || p.multiplier != 0 || p.shift != 0) errors.push_back("op " + std::to_string(index) + ": non-requantized QGEMM must produce int32 with zero multiplier/shift");
        else if (!scales_equal(out.scale, static_cast<float>(static_cast<double>(a.scale) * w.scale))) errors.push_back("op " + std::to_string(index) + ": int32 output scale must equal input scale times weight scale");
        break;
      }
      case Opcode::QCONV2D: {
        require_arity(3, 1);
        if (operation.inputs.size() != 3 || operation.outputs.size() != 1 ||
            !std::holds_alternative<QConv2DParams>(operation.params)) {
          errors.push_back("op " + std::to_string(index) + ": malformed QCONV2D");
          break;
        }
        const Tensor& a = find_tensor(graph, operation.inputs[0]);
        const Tensor& w = find_tensor(graph, operation.inputs[1]);
        const Tensor& b = find_tensor(graph, operation.inputs[2]);
        const Tensor& out = find_tensor(graph, operation.outputs[0]);
        const QConv2DParams p = std::get<QConv2DParams>(operation.params);
        const std::string prefix = "op " + std::to_string(index) + ": ";

        if ((a.flags & TINY3TPU_TENSOR_CONSTANT) != 0 ||
            a.dtype != DType::I8 || a.layout != Layout::NHWC ||
            a.shape.size() != 4)
          errors.push_back(prefix + "QCONV2D activation must be nonconstant rank-4 NHWC int8");
        if (w.dtype != DType::I8 || w.flags != TINY3TPU_TENSOR_CONSTANT ||
            w.layout != Layout::Packed || w.shape.size() != 4)
          errors.push_back(prefix + "QCONV2D weight must be constant rank-4 packed int8 HWIO");
        if (b.dtype != DType::I32 || b.flags != TINY3TPU_TENSOR_CONSTANT ||
            b.layout != Layout::Packed || b.shape.size() != 1)
          errors.push_back(prefix + "QCONV2D bias must be constant packed rank-1 int32");
        if (out.layout != Layout::NHWC || out.shape.size() != 4 ||
            (out.flags & (TINY3TPU_TENSOR_INPUT | TINY3TPU_TENSOR_CONSTANT |
                          TINY3TPU_TENSOR_SCRATCH)) != 0)
          errors.push_back(prefix + "QCONV2D output must be non-input, nonconstant, non-scratch rank-4 NHWC");

        if (p.groups != 1 || p.kernel_h == 0 || p.kernel_w == 0 ||
            p.stride_h == 0 || p.stride_w == 0 || p.shift > 62 ||
            (p.flags & ~(TINY3TPU_QGEMM_FLAG_REQUANT |
                         TINY3TPU_QGEMM_FLAG_RELU)) != 0)
          errors.push_back(prefix + "invalid QCONV2D parameters");

        const bool ranks_valid = a.shape.size() == 4 && w.shape.size() == 4 &&
                                 b.shape.size() == 1 && out.shape.size() == 4;
        if (!ranks_valid) break;

        uint32_t output_height = 0;
        uint32_t output_width = 0;
        const bool spatial_valid =
            spatial_output_dimension(a.shape[1], p.pad_top, p.pad_bottom,
                                     p.kernel_h, p.stride_h, output_height) &&
            spatial_output_dimension(a.shape[2], p.pad_left, p.pad_right,
                                     p.kernel_w, p.stride_w, output_width);
        if (!spatial_valid || w.shape[0] != p.kernel_h ||
            w.shape[1] != p.kernel_w || w.shape[2] != a.shape[3] ||
            b.shape[0] != w.shape[3] || out.shape[0] != a.shape[0] ||
            out.shape[1] != output_height || out.shape[2] != output_width ||
            out.shape[3] != w.shape[3])
          errors.push_back(prefix + "QCONV2D NHWC/HWIO shapes do not match parameters");

        float accumulator_scale = 0.0f;
        const bool scales_valid =
            checked_scale_product(a.scale, w.scale, accumulator_scale) &&
            scales_equal(b.scale, accumulator_scale);
        if (!scales_valid)
          errors.push_back(prefix + "QCONV2D bias scale must equal input scale times weight scale");

        const bool requantize = (p.flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0;
        if (requantize) {
          if (out.dtype != DType::I8 ||
              !multiplier_matches(static_cast<double>(a.scale) * w.scale /
                                       out.scale,
                                   p.multiplier, p.shift))
            errors.push_back(prefix + "QCONV2D requantization is inconsistent with tensor scales");
        } else if (out.dtype != DType::I32 || p.multiplier != 0 || p.shift != 0 ||
                   !scales_equal(out.scale, accumulator_scale)) {
          errors.push_back(prefix + "non-requantized QCONV2D must produce int32 with zero multiplier/shift and accumulator scale");
        }
        if ((p.flags & TINY3TPU_QGEMM_FLAG_RELU) != 0 && out.dtype != DType::I8)
          errors.push_back(prefix + "ReLU on int32 QCONV2D output is unsupported");

        uint32_t weight_elements = 0;
        uint32_t bias_elements = 0;
        const bool valid_constant_data =
            try_element_count(w.shape, weight_elements) &&
            try_element_count(b.shape, bias_elements) &&
            w.data.size() == weight_elements && b.data.size() == bias_elements;
        if (valid_constant_data &&
            !conservative_image_accumulator_bound(a, w, b))
          errors.push_back(prefix + "int32 QCONV2D accumulation may overflow");
        break;
      }
      case Opcode::MAX_POOL_2D: {
        require_arity(1, 1);
        if (operation.inputs.size() != 1 || operation.outputs.size() != 1 ||
            !std::holds_alternative<MaxPool2DParams>(operation.params)) {
          errors.push_back("op " + std::to_string(index) + ": malformed MAX_POOL_2D");
          break;
        }
        const Tensor& a = find_tensor(graph, operation.inputs[0]);
        const Tensor& out = find_tensor(graph, operation.outputs[0]);
        const MaxPool2DParams p = std::get<MaxPool2DParams>(operation.params);
        const std::string prefix = "op " + std::to_string(index) + ": ";
        if ((a.flags & TINY3TPU_TENSOR_CONSTANT) != 0 ||
            a.dtype != DType::I8 || a.layout != Layout::NHWC ||
            a.shape.size() != 4)
          errors.push_back(prefix + "MAX_POOL_2D input must be nonconstant rank-4 NHWC int8");
        if (out.dtype != DType::I8 || out.layout != Layout::NHWC ||
            out.shape.size() != 4 ||
            (out.flags & (TINY3TPU_TENSOR_INPUT | TINY3TPU_TENSOR_CONSTANT |
                          TINY3TPU_TENSOR_SCRATCH)) != 0)
          errors.push_back(prefix + "MAX_POOL_2D output must be non-input, nonconstant, non-scratch rank-4 NHWC int8");
        if (p.kernel_h == 0 || p.kernel_w == 0 || p.stride_h == 0 ||
            p.stride_w == 0)
          errors.push_back(prefix + "invalid MAX_POOL_2D kernel or stride");
        if (a.shape.size() != 4 || out.shape.size() != 4) break;

        uint32_t output_height = 0;
        uint32_t output_width = 0;
        if (!spatial_output_dimension(a.shape[1], p.pad_top, p.pad_bottom,
                                      p.kernel_h, p.stride_h, output_height) ||
            !spatial_output_dimension(a.shape[2], p.pad_left, p.pad_right,
                                      p.kernel_w, p.stride_w, output_width) ||
            out.shape[0] != a.shape[0] || out.shape[1] != output_height ||
            out.shape[2] != output_width || out.shape[3] != a.shape[3])
          errors.push_back(prefix + "MAX_POOL_2D NHWC shapes do not match parameters");
        if (scalar_bits(a.scale) != scalar_bits(out.scale))
          errors.push_back(prefix + "MAX_POOL_2D input and output scales must match exactly");
        break;
      }
      case Opcode::RESHAPE: {
        require_arity(1,1);
        if (!std::holds_alternative<ReshapeParams>(operation.params)) errors.push_back("op "+std::to_string(index)+": malformed RESHAPE params");
        else if (operation.inputs.size()==1&&operation.outputs.size()==1) {
          const Tensor& source=find_tensor(graph,operation.inputs[0]); const Tensor& destination=find_tensor(graph,operation.outputs[0]); const auto& shape=std::get<ReshapeParams>(operation.params).shape;
          uint32_t source_count=0, destination_count=0, reshape_count=0;
          if (!try_element_count(source.shape, source_count) || !try_element_count(destination.shape, destination_count) || !try_element_count(shape, reshape_count) ||
              shape.size()>TINY3TPU_MAX_RANK || source.dtype!=destination.dtype || source.layout!=destination.layout || !scales_equal(source.scale,destination.scale) || source.zero_point!=destination.zero_point ||
              destination.shape!=shape || source_count!=destination_count || source_count!=reshape_count)
            errors.push_back("op "+std::to_string(index)+": invalid RESHAPE descriptor");
        }
        break;
      }
      case Opcode::ARGMAX: { require_arity(1,1); if (!std::holds_alternative<ArgmaxParams>(operation.params)||std::get<ArgmaxParams>(operation.params).axis!=0) errors.push_back("op "+std::to_string(index)+": only ARGMAX axis 0 is supported"); else if (operation.inputs.size()==1&&operation.outputs.size()==1) { const auto& source=find_tensor(graph,operation.inputs[0]); const auto& destination=find_tensor(graph,operation.outputs[0]); if(source.shape.size()!=1||destination.dtype!=DType::I32||destination.shape!=std::vector<uint32_t>{1}) errors.push_back("op "+std::to_string(index)+": ARGMAX requires rank-1 input and int32 [1] output"); } break; }
      default: errors.push_back("op " + std::to_string(index) + ": unknown opcode"); break;
    }
    for (uint32_t id : operation.outputs) if (known(id)) produced.insert(id);
  }
  for (uint32_t id : graph.outputs) if (known(id) && !produced.count(id)) errors.push_back("graph output was never produced: " + std::to_string(id));
  return errors;
}

CompiledModel compile_graph(Graph graph) {
  const auto errors = validate(graph);
  if (!errors.empty()) { std::string message="invalid graph:"; for(const auto& error:errors) message += "\n - " + error; throw std::runtime_error(message); }
  Writer output; output.zero(TINY3TPU_MODEL_HEADER_BYTES);
  const uint32_t tensor_offset=static_cast<uint32_t>(output.bytes.size()); for(const Tensor& tensor:graph.tensors) (void)tensor, output.zero(TINY3TPU_MODEL_TENSOR_RECORD_BYTES);
  const uint32_t operation_offset=static_cast<uint32_t>(output.bytes.size()); for(const Operation& operation:graph.operations) (void)operation, output.zero(TINY3TPU_MODEL_OPERATION_RECORD_BYTES);
  const uint32_t parameter_offset=static_cast<uint32_t>(output.bytes.size()); std::vector<uint32_t> parameter_sizes;
  for (const Operation& operation : graph.operations) { Writer params; if(operation.opcode==Opcode::QGEMM){auto p=std::get<QGemmParams>(operation.params);params.i32(p.multiplier);params.u32(p.shift);params.u32(p.flags);params.u32(0);} else if(operation.opcode==Opcode::QCONV2D){auto p=std::get<QConv2DParams>(operation.params);params.u32(p.stride_h);params.u32(p.stride_w);params.u32(p.pad_top);params.u32(p.pad_left);params.u32(p.pad_bottom);params.u32(p.pad_right);params.u32(p.kernel_h);params.u32(p.kernel_w);params.u32(p.groups);params.i32(p.multiplier);params.u32(p.shift);params.u32(p.flags);params.u32(0);} else if(operation.opcode==Opcode::MAX_POOL_2D){auto p=std::get<MaxPool2DParams>(operation.params);params.u32(p.kernel_h);params.u32(p.kernel_w);params.u32(p.stride_h);params.u32(p.stride_w);params.u32(p.pad_top);params.u32(p.pad_left);params.u32(p.pad_bottom);params.u32(p.pad_right);params.u32(0);} else if(operation.opcode==Opcode::RESHAPE){auto p=std::get<ReshapeParams>(operation.params);params.u32(static_cast<uint32_t>(p.shape.size()));for(unsigned i=0;i<4;++i)params.u32(i<p.shape.size()?p.shape[i]:0);params.u32(0);} else {params.u32(std::get<ArgmaxParams>(operation.params).axis);params.u32(0);} parameter_sizes.push_back(static_cast<uint32_t>(params.bytes.size())); output.bytes.insert(output.bytes.end(),params.bytes.begin(),params.bytes.end()); }
  output.align(4); const uint32_t constant_offset=static_cast<uint32_t>(output.bytes.size()); std::vector<uint32_t> data_offsets(graph.tensors.size()),data_sizes(graph.tensors.size());
  for(size_t i=0;i<graph.tensors.size();++i){const Tensor&t=graph.tensors[i];if(!(t.flags&TINY3TPU_TENSOR_CONSTANT))continue;output.align(4);data_offsets[i]=static_cast<uint32_t>(output.bytes.size());if(t.dtype==DType::I32)for(int32_t v:t.data)output.i32(v);else for(int32_t v:t.data)output.u8(static_cast<uint8_t>(v));data_sizes[i]=static_cast<uint32_t>(output.bytes.size()-data_offsets[i]);}
  output.align(16); const uint32_t arena_offset=static_cast<uint32_t>(output.bytes.size()); uint32_t arena_size=0;
  for(size_t i=0;i<graph.tensors.size();++i){Tensor&t=graph.tensors[i];if(t.flags&TINY3TPU_TENSOR_CONSTANT)continue;arena_size=align_up(arena_size,16);data_offsets[i]=checked_add(arena_offset,arena_size,"arena offset");data_sizes[i]=checked_mul(element_count(t.shape),dtype_bytes(t.dtype),"tensor bytes");arena_size=checked_add(arena_size,align_up(data_sizes[i],16),"arena size");}
  output.zero(arena_size);
  for(size_t i=0;i<graph.tensors.size();++i){Writer record;write_tensor_record(record,graph.tensors[i],data_offsets[i],data_sizes[i]);std::copy(record.bytes.begin(),record.bytes.end(),output.bytes.begin()+tensor_offset+i*TINY3TPU_MODEL_TENSOR_RECORD_BYTES);}
  uint32_t parameter_cursor=parameter_offset;for(size_t i=0;i<graph.operations.size();++i){Writer record;record.u32(static_cast<uint32_t>(graph.operations[i].opcode));record.u32(1);for(unsigned j=0;j<3;++j)record.u32(j<graph.operations[i].inputs.size()?graph.operations[i].inputs[j]:UINT32_MAX);for(unsigned j=0;j<2;++j)record.u32(j<graph.operations[i].outputs.size()?graph.operations[i].outputs[j]:UINT32_MAX);record.u32(parameter_cursor);record.u32(parameter_sizes[i]);record.u32(0);std::copy(record.bytes.begin(),record.bytes.end(),output.bytes.begin()+operation_offset+i*TINY3TPU_MODEL_OPERATION_RECORD_BYTES);parameter_cursor=checked_add(parameter_cursor,parameter_sizes[i],"parameter offset");}
  write_u32(output.bytes, TINY3TPU_HEADER_MAGIC_OFFSET, TINY3TPU_MODEL_MAGIC);
  write_u32(output.bytes, TINY3TPU_HEADER_VERSION_OFFSET, TINY3TPU_MODEL_VERSION);
  write_u32(output.bytes, TINY3TPU_HEADER_BYTES_OFFSET, TINY3TPU_MODEL_HEADER_BYTES);
  write_u32(output.bytes, TINY3TPU_HEADER_TOTAL_BYTES_OFFSET, static_cast<uint32_t>(output.bytes.size()));
  write_u32(output.bytes, TINY3TPU_HEADER_TENSOR_COUNT_OFFSET, static_cast<uint32_t>(graph.tensors.size()));
  write_u32(output.bytes, TINY3TPU_HEADER_OPERATION_COUNT_OFFSET, static_cast<uint32_t>(graph.operations.size()));
  write_u32(output.bytes, TINY3TPU_HEADER_TENSOR_TABLE_OFFSET, tensor_offset);
  write_u32(output.bytes, TINY3TPU_HEADER_OPERATION_TABLE_OFFSET, operation_offset);
  write_u32(output.bytes, TINY3TPU_HEADER_PARAMETER_OFFSET, parameter_offset);
  write_u32(output.bytes, TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET, parameter_cursor - parameter_offset);
  write_u32(output.bytes, TINY3TPU_HEADER_CONSTANT_OFFSET, constant_offset);
  write_u32(output.bytes, TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET, arena_offset - constant_offset);
  write_u32(output.bytes, TINY3TPU_HEADER_ARENA_OFFSET, arena_offset);
  write_u32(output.bytes, TINY3TPU_HEADER_ARENA_BYTES_OFFSET, arena_size);
  // The currently supported host operations need no independent scratch.
  write_u32(output.bytes, TINY3TPU_HEADER_SCRATCH_OFFSET, 0);
  write_u32(output.bytes, TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET, 0);
  write_u32(output.bytes, TINY3TPU_HEADER_INPUT_COUNT_OFFSET, static_cast<uint32_t>(graph.inputs.size()));
  write_u32(output.bytes, TINY3TPU_HEADER_OUTPUT_COUNT_OFFSET, static_cast<uint32_t>(graph.outputs.size()));
  write_u32(output.bytes, TINY3TPU_HEADER_FLAGS_OFFSET, 0);
  write_u32(output.bytes, TINY3TPU_HEADER_CRC32_OFFSET, 0);
  write_u32(output.bytes, TINY3TPU_HEADER_CRC32_OFFSET, crc32(output.bytes));
  return CompiledModel{std::move(graph), std::move(output.bytes)};
}

static bool validate_qgemm_wire_semantics(
    const std::vector<uint8_t>& bytes, size_t operation_index, uint32_t parameter_offset,
    uint32_t parameter_bytes,
    uint32_t input_id, uint32_t weight_id, uint32_t bias_id, uint32_t output_id,
    const std::unordered_map<uint32_t, uint8_t>& tensor_flags,
    const std::unordered_map<uint32_t, uint8_t>& layouts,
    const std::unordered_map<uint32_t, std::vector<uint32_t>>& shapes,
    const std::unordered_map<uint32_t, uint8_t>& dtypes,
    const std::unordered_map<uint32_t, float>& scales,
    const std::unordered_map<uint32_t, uint32_t>& byte_offsets,
    const std::unordered_map<uint32_t, uint32_t>& byte_sizes, std::string& error) {
  const std::string prefix = "op " + std::to_string(operation_index) + ": ";
  auto fail = [&](const std::string& message) {
    error = prefix + message;
    return false;
  };
  const auto flags_for = tensor_flags.find(input_id);
  const auto weight_flags = tensor_flags.find(weight_id);
  const auto bias_flags = tensor_flags.find(bias_id);
  const auto output_flags = tensor_flags.find(output_id);
  const auto input_layout = layouts.find(input_id);
  const auto weight_layout = layouts.find(weight_id);
  const auto bias_layout = layouts.find(bias_id);
  const auto output_layout = layouts.find(output_id);
  const auto input_shape = shapes.find(input_id);
  const auto weight_shape = shapes.find(weight_id);
  const auto bias_shape = shapes.find(bias_id);
  const auto output_shape = shapes.find(output_id);
  const auto input_dtype = dtypes.find(input_id);
  const auto weight_dtype = dtypes.find(weight_id);
  const auto bias_dtype = dtypes.find(bias_id);
  const auto output_dtype = dtypes.find(output_id);
  const auto input_scale = scales.find(input_id);
  const auto weight_scale = scales.find(weight_id);
  const auto bias_scale = scales.find(bias_id);
  const auto output_scale = scales.find(output_id);
  const auto weight_offset = byte_offsets.find(weight_id);
  const auto bias_offset = byte_offsets.find(bias_id);
  const auto weight_bytes = byte_sizes.find(weight_id);
  const auto bias_bytes = byte_sizes.find(bias_id);
  if (flags_for == tensor_flags.end() || weight_flags == tensor_flags.end() ||
      bias_flags == tensor_flags.end() || output_flags == tensor_flags.end() ||
      input_layout == layouts.end() || weight_layout == layouts.end() ||
      bias_layout == layouts.end() || output_layout == layouts.end() ||
      input_shape == shapes.end() || weight_shape == shapes.end() ||
      bias_shape == shapes.end() || output_shape == shapes.end() ||
      input_dtype == dtypes.end() || weight_dtype == dtypes.end() ||
      bias_dtype == dtypes.end() || output_dtype == dtypes.end() ||
      input_scale == scales.end() || weight_scale == scales.end() ||
      bias_scale == scales.end() || output_scale == scales.end() ||
      weight_offset == byte_offsets.end() || bias_offset == byte_offsets.end() ||
      weight_bytes == byte_sizes.end() || bias_bytes == byte_sizes.end())
    return fail("QGEMM references missing tensor metadata");

  if (parameter_offset > bytes.size() || parameter_bytes != TINY3TPU_QGEMM_PARAMETER_BYTES ||
      parameter_bytes > bytes.size() - parameter_offset)
    return fail("QGEMM parameter record is truncated");
  const uint32_t multiplier_bits = read_u32(bytes, parameter_offset);
  const int32_t multiplier = static_cast<int32_t>(multiplier_bits);
  const uint32_t shift = read_u32(bytes, parameter_offset + 4);
  const uint32_t flags = read_u32(bytes, parameter_offset + 8);
  if (shift > 62) return fail("invalid QGEMM shift");
  if ((flags & ~(TINY3TPU_QGEMM_FLAG_REQUANT |
                 TINY3TPU_QGEMM_FLAG_RELU |
                 TINY3TPU_QGEMM_FLAG_WEIGHT_OUT_IN)) != 0)
    return fail("unknown QGEMM flags");
  if (read_u32(bytes, parameter_offset + 12) != 0)
    return fail("nonzero QGEMM parameter reserved field");

  if ((input_dtype->second != TINY3TPU_DTYPE_I8 && input_dtype->second != TINY3TPU_DTYPE_U8) ||
      weight_dtype->second != TINY3TPU_DTYPE_I8 ||
      weight_flags->second != TINY3TPU_TENSOR_CONSTANT ||
      bias_dtype->second != TINY3TPU_DTYPE_I32 ||
      bias_flags->second != TINY3TPU_TENSOR_CONSTANT ||
      (flags_for->second & (TINY3TPU_TENSOR_CONSTANT | TINY3TPU_TENSOR_SCRATCH)) != 0)
    return fail("QGEMM operands have incompatible dtypes or constant status");
  if (input_layout->second != TINY3TPU_LAYOUT_PACKED ||
      weight_layout->second != TINY3TPU_LAYOUT_PACKED ||
      bias_layout->second != TINY3TPU_LAYOUT_PACKED ||
      output_layout->second != TINY3TPU_LAYOUT_PACKED)
    return fail("QGEMM requires packed tensors");
  if ((output_flags->second & (TINY3TPU_TENSOR_INPUT |
                               TINY3TPU_TENSOR_CONSTANT |
                               TINY3TPU_TENSOR_SCRATCH)) != 0)
    return fail("QGEMM output must be a non-input, nonconstant, non-scratch tensor");
  if (input_shape->second.size() < 1 || input_shape->second.size() > 2 ||
      weight_shape->second.size() != 2 || bias_shape->second.size() != 1 ||
      output_shape->second.size() < 1 || output_shape->second.size() > 2)
    return fail("QGEMM operands have incompatible ranks");

  const uint32_t k = weight_shape->second[1];
  const uint32_t n = weight_shape->second[0];
  const uint32_t m = input_shape->second.size() == 1 ? 1 : input_shape->second[0];
  uint64_t weight_elements = 1;
  uint64_t bias_elements = 1;
  for (uint32_t dimension : weight_shape->second) weight_elements *= dimension;
  for (uint32_t dimension : bias_shape->second) bias_elements *= dimension;
  if (weight_elements > UINT32_MAX || bias_elements > UINT32_MAX ||
      weight_bytes->second != weight_elements ||
      bias_bytes->second != bias_elements * sizeof(int32_t))
    return fail("QGEMM constant tensor byte size does not match its shape and dtype");
  const bool output_shape_matches =
      input_shape->second.back() == k && bias_shape->second[0] == n &&
      (output_shape->second.size() == 1
           ? (m == 1 && output_shape->second[0] == n)
           : (output_shape->second[0] == m && output_shape->second[1] == n));
  if (!output_shape_matches) return fail("QGEMM operand/output shapes do not match");

  const uint64_t input_abs = input_dtype->second == TINY3TPU_DTYPE_U8 ? 255U : 128U;
  for (uint32_t output = 0; output < n; ++output) {
    uint64_t worst = 0;
    for (uint32_t input = 0; input < k; ++input) {
      const size_t weight_position = static_cast<size_t>(weight_offset->second) +
                                     static_cast<size_t>(output) * k + input;
      const int32_t weight = static_cast<int8_t>(bytes[weight_position]);
      const uint64_t magnitude = weight < 0 ? uint64_t(-(int64_t)weight) : uint64_t(weight);
      if (magnitude > (UINT64_MAX - worst) / input_abs)
        return fail("QGEMM int32 accumulation bound overflow");
      worst += magnitude * input_abs;
    }
    const size_t bias_position = static_cast<size_t>(bias_offset->second) +
                                 static_cast<size_t>(output) * sizeof(int32_t);
    const int32_t bias = static_cast<int32_t>(read_u32(bytes, bias_position));
    const uint64_t bias_magnitude = bias < 0 ? uint64_t(-(int64_t)bias) : uint64_t(bias);
    if (bias_magnitude > UINT64_MAX - worst ||
        worst + bias_magnitude > static_cast<uint64_t>(std::numeric_limits<int32_t>::max()))
      return fail("int32 accumulation may overflow");
  }

  const double accumulator_scale = static_cast<double>(input_scale->second) * weight_scale->second;
  if (!std::isfinite(accumulator_scale) || accumulator_scale <= 0.0 ||
      accumulator_scale > static_cast<double>(std::numeric_limits<float>::max()))
    return fail("QGEMM accumulator scale is not representable");
  if (!scales_equal(bias_scale->second, static_cast<float>(accumulator_scale)))
    return fail("QGEMM bias scale does not match accumulator scale");
  const bool requantize = (flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0;
  if (requantize) {
    if (output_dtype->second != TINY3TPU_DTYPE_I8)
      return fail("requantized QGEMM output must be int8");
    if (!multiplier_matches(accumulator_scale / output_scale->second, multiplier, shift))
      return fail("QGEMM multiplier does not match output scale");
  } else {
    if (output_dtype->second != TINY3TPU_DTYPE_I32 || multiplier != 0 || shift != 0)
      return fail("non-requantized QGEMM must produce int32 with zero multiplier/shift");
    if (!scales_equal(output_scale->second, static_cast<float>(accumulator_scale)))
      return fail("non-requantized QGEMM output scale does not match accumulator scale");
  }
  if ((flags & TINY3TPU_QGEMM_FLAG_RELU) != 0 && output_dtype->second != TINY3TPU_DTYPE_I8)
    return fail("ReLU on int32 QGEMM output is unsupported");
  return true;
}

static bool validate_qconv2d_wire_semantics(
    const std::vector<uint8_t>& bytes, size_t operation_index,
    uint32_t parameter_offset, uint32_t parameter_bytes, uint32_t input_id,
    uint32_t weight_id, uint32_t bias_id, uint32_t output_id,
    const std::unordered_map<uint32_t, uint8_t>& tensor_flags,
    const std::unordered_map<uint32_t, uint8_t>& layouts,
    const std::unordered_map<uint32_t, std::vector<uint32_t>>& shapes,
    const std::unordered_map<uint32_t, uint8_t>& dtypes,
    const std::unordered_map<uint32_t, float>& scales,
    const std::unordered_map<uint32_t, uint32_t>& byte_offsets,
    const std::unordered_map<uint32_t, uint32_t>& byte_sizes,
    std::string& error) {
  const std::string prefix = "op " + std::to_string(operation_index) + ": ";
  auto fail = [&](const std::string& message) {
    error = prefix + message;
    return false;
  };
  const auto has_metadata = [&](uint32_t id) {
    return tensor_flags.count(id) != 0 && layouts.count(id) != 0 &&
           shapes.count(id) != 0 && dtypes.count(id) != 0 &&
           scales.count(id) != 0 && byte_offsets.count(id) != 0 &&
           byte_sizes.count(id) != 0;
  };
  if (!has_metadata(input_id) || !has_metadata(weight_id) ||
      !has_metadata(bias_id) || !has_metadata(output_id))
    return fail("QCONV2D references missing tensor metadata");
  if (parameter_offset > bytes.size() ||
      parameter_bytes != TINY3TPU_QCONV2D_PARAMETER_BYTES ||
      parameter_bytes > bytes.size() - parameter_offset)
    return fail("QCONV2D parameter record is truncated");

  const uint32_t stride_h =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_STRIDE_H_OFFSET);
  const uint32_t stride_w =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_STRIDE_W_OFFSET);
  const uint32_t pad_top =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_PAD_TOP_OFFSET);
  const uint32_t pad_left =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_PAD_LEFT_OFFSET);
  const uint32_t pad_bottom =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_PAD_BOTTOM_OFFSET);
  const uint32_t pad_right =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_PAD_RIGHT_OFFSET);
  const uint32_t kernel_h =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_KERNEL_H_OFFSET);
  const uint32_t kernel_w =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_KERNEL_W_OFFSET);
  const uint32_t groups =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_GROUPS_OFFSET);
  const int32_t multiplier = static_cast<int32_t>(read_u32(
      bytes, parameter_offset + TINY3TPU_QCONV2D_MULTIPLIER_OFFSET));
  const uint32_t shift =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_SHIFT_OFFSET);
  const uint32_t flags =
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_FLAGS_OFFSET);
  if (stride_h == 0 || stride_w == 0 || kernel_h == 0 || kernel_w == 0 ||
      groups != 1 || shift > 62 ||
      (flags & ~(TINY3TPU_QGEMM_FLAG_REQUANT |
                 TINY3TPU_QGEMM_FLAG_RELU)) != 0 ||
      read_u32(bytes, parameter_offset + TINY3TPU_QCONV2D_RESERVED_OFFSET) != 0)
    return fail("invalid QCONV2D parameters");
  if ((flags & TINY3TPU_QGEMM_FLAG_REQUANT) == 0) {
    if (multiplier != 0 || shift != 0)
      return fail("non-requantized QCONV2D must have zero multiplier/shift");
  } else if (multiplier <= 0) {
    return fail("requantized QCONV2D multiplier must be positive");
  }

  const auto& input_shape = shapes.at(input_id);
  const auto& weight_shape = shapes.at(weight_id);
  const auto& bias_shape = shapes.at(bias_id);
  const auto& output_shape = shapes.at(output_id);
  if ((tensor_flags.at(input_id) & TINY3TPU_TENSOR_CONSTANT) != 0 ||
      dtypes.at(input_id) != TINY3TPU_DTYPE_I8 ||
      layouts.at(input_id) != TINY3TPU_LAYOUT_NHWC || input_shape.size() != 4 ||
      dtypes.at(weight_id) != TINY3TPU_DTYPE_I8 ||
      tensor_flags.at(weight_id) != TINY3TPU_TENSOR_CONSTANT ||
      layouts.at(weight_id) != TINY3TPU_LAYOUT_PACKED ||
      weight_shape.size() != 4 || dtypes.at(bias_id) != TINY3TPU_DTYPE_I32 ||
      tensor_flags.at(bias_id) != TINY3TPU_TENSOR_CONSTANT ||
      layouts.at(bias_id) != TINY3TPU_LAYOUT_PACKED || bias_shape.size() != 1 ||
      layouts.at(output_id) != TINY3TPU_LAYOUT_NHWC || output_shape.size() != 4 ||
      (tensor_flags.at(output_id) & (TINY3TPU_TENSOR_INPUT |
                                     TINY3TPU_TENSOR_CONSTANT |
                                     TINY3TPU_TENSOR_SCRATCH)) != 0)
    return fail("QCONV2D operands have incompatible dtypes, layouts, ranks, or flags");

  uint32_t output_height = 0;
  uint32_t output_width = 0;
  if (!spatial_output_dimension(input_shape[1], pad_top, pad_bottom, kernel_h,
                                stride_h, output_height) ||
      !spatial_output_dimension(input_shape[2], pad_left, pad_right, kernel_w,
                                stride_w, output_width) ||
      weight_shape[0] != kernel_h || weight_shape[1] != kernel_w ||
      weight_shape[2] != input_shape[3] || bias_shape[0] != weight_shape[3] ||
      output_shape[0] != input_shape[0] || output_shape[1] != output_height ||
      output_shape[2] != output_width || output_shape[3] != weight_shape[3])
    return fail("QCONV2D NHWC/HWIO shapes do not match parameters");

  uint32_t weight_elements = 0;
  uint32_t bias_elements = 0;
  if (!try_element_count(weight_shape, weight_elements) ||
      !try_element_count(bias_shape, bias_elements) ||
      byte_sizes.at(weight_id) != weight_elements ||
      byte_sizes.at(bias_id) != bias_elements * sizeof(int32_t))
    return fail("QCONV2D constant tensor byte size does not match shape/dtype");
  for (uint32_t output = 0; output < weight_shape[3]; ++output) {
    uint64_t worst = 0;
    for (uint32_t kh = 0; kh < kernel_h; ++kh) {
      for (uint32_t kw = 0; kw < kernel_w; ++kw) {
        for (uint32_t input = 0; input < input_shape[3]; ++input) {
          const size_t position = static_cast<size_t>(byte_offsets.at(weight_id)) +
              (((static_cast<size_t>(kh) * kernel_w + kw) * input_shape[3] + input) *
               weight_shape[3] + output);
          const int32_t value = static_cast<int8_t>(bytes[position]);
          const uint64_t magnitude =
              value < 0 ? uint64_t(-(int64_t)value) : uint64_t(value);
          if (magnitude > (UINT64_MAX - worst) / 128U) return fail("QCONV2D accumulation bound overflow");
          worst += magnitude * 128U;
        }
      }
    }
    const size_t bias_position = static_cast<size_t>(byte_offsets.at(bias_id)) +
                                 static_cast<size_t>(output) * sizeof(int32_t);
    const int32_t bias = static_cast<int32_t>(read_u32(bytes, bias_position));
    const uint64_t bias_magnitude =
        bias < 0 ? uint64_t(-(int64_t)bias) : uint64_t(bias);
    if (bias_magnitude > UINT64_MAX - worst ||
        worst + bias_magnitude > static_cast<uint64_t>(INT32_MAX))
      return fail("QCONV2D int32 accumulation may overflow");
  }

  float accumulator_scale = 0.0f;
  if (!checked_scale_product(scales.at(input_id), scales.at(weight_id),
                             accumulator_scale) ||
      !scales_equal(scales.at(bias_id), accumulator_scale))
    return fail("QCONV2D bias scale does not match accumulator scale");
  const bool requantize = (flags & TINY3TPU_QGEMM_FLAG_REQUANT) != 0;
  if (requantize) {
    if (dtypes.at(output_id) != TINY3TPU_DTYPE_I8 ||
        !multiplier_matches(static_cast<double>(scales.at(input_id)) *
                                scales.at(weight_id) / scales.at(output_id),
                            multiplier, shift))
      return fail("QCONV2D multiplier does not match output scale");
  } else if (dtypes.at(output_id) != TINY3TPU_DTYPE_I32 ||
             !scales_equal(scales.at(output_id), accumulator_scale)) {
    return fail("non-requantized QCONV2D output must be int32 at accumulator scale");
  }
  if ((flags & TINY3TPU_QGEMM_FLAG_RELU) != 0 &&
      dtypes.at(output_id) != TINY3TPU_DTYPE_I8)
    return fail("ReLU on int32 QCONV2D output is unsupported");
  return true;
}

static bool validate_max_pool2d_wire_semantics(
    const std::vector<uint8_t>& bytes, size_t operation_index,
    uint32_t parameter_offset, uint32_t parameter_bytes, uint32_t input_id,
    uint32_t output_id, const std::unordered_map<uint32_t, uint8_t>& tensor_flags,
    const std::unordered_map<uint32_t, uint8_t>& layouts,
    const std::unordered_map<uint32_t, std::vector<uint32_t>>& shapes,
    const std::unordered_map<uint32_t, uint8_t>& dtypes,
    const std::unordered_map<uint32_t, float>& scales, std::string& error) {
  const std::string prefix = "op " + std::to_string(operation_index) + ": ";
  auto fail = [&](const std::string& message) {
    error = prefix + message;
    return false;
  };
  if (parameter_offset > bytes.size() ||
      parameter_bytes != TINY3TPU_MAX_POOL2D_PARAMETER_BYTES ||
      parameter_bytes > bytes.size() - parameter_offset)
    return fail("MAX_POOL_2D parameter record is truncated");
  const uint32_t kernel_h = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_KERNEL_H_OFFSET);
  const uint32_t kernel_w = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_KERNEL_W_OFFSET);
  const uint32_t stride_h = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_STRIDE_H_OFFSET);
  const uint32_t stride_w = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_STRIDE_W_OFFSET);
  const uint32_t pad_top = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_PAD_TOP_OFFSET);
  const uint32_t pad_left = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_PAD_LEFT_OFFSET);
  const uint32_t pad_bottom = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_PAD_BOTTOM_OFFSET);
  const uint32_t pad_right = read_u32(
      bytes, parameter_offset + TINY3TPU_MAX_POOL2D_PAD_RIGHT_OFFSET);
  if (kernel_h == 0 || kernel_w == 0 || stride_h == 0 || stride_w == 0 ||
      read_u32(bytes, parameter_offset + TINY3TPU_MAX_POOL2D_RESERVED_OFFSET) != 0)
    return fail("invalid MAX_POOL_2D parameters");
  if (tensor_flags.count(input_id) == 0 || tensor_flags.count(output_id) == 0 ||
      layouts.count(input_id) == 0 || layouts.count(output_id) == 0 ||
      shapes.count(input_id) == 0 || shapes.count(output_id) == 0 ||
      dtypes.count(input_id) == 0 || dtypes.count(output_id) == 0 ||
      scales.count(input_id) == 0 || scales.count(output_id) == 0)
    return fail("MAX_POOL_2D references missing tensor metadata");
  const auto& input_shape = shapes.at(input_id);
  const auto& output_shape = shapes.at(output_id);
  if ((tensor_flags.at(input_id) & TINY3TPU_TENSOR_CONSTANT) != 0 ||
      dtypes.at(input_id) != TINY3TPU_DTYPE_I8 ||
      layouts.at(input_id) != TINY3TPU_LAYOUT_NHWC || input_shape.size() != 4 ||
      dtypes.at(output_id) != TINY3TPU_DTYPE_I8 ||
      layouts.at(output_id) != TINY3TPU_LAYOUT_NHWC || output_shape.size() != 4 ||
      (tensor_flags.at(output_id) & (TINY3TPU_TENSOR_INPUT |
                                     TINY3TPU_TENSOR_CONSTANT |
                                     TINY3TPU_TENSOR_SCRATCH)) != 0)
    return fail("MAX_POOL_2D operands have incompatible dtypes, layouts, ranks, or flags");
  uint32_t output_height = 0;
  uint32_t output_width = 0;
  if (!spatial_output_dimension(input_shape[1], pad_top, pad_bottom, kernel_h,
                                stride_h, output_height) ||
      !spatial_output_dimension(input_shape[2], pad_left, pad_right, kernel_w,
                                stride_w, output_width) ||
      output_shape[0] != input_shape[0] || output_shape[1] != output_height ||
      output_shape[2] != output_width || output_shape[3] != input_shape[3])
    return fail("MAX_POOL_2D NHWC shapes do not match parameters");
  if (scalar_bits(scales.at(input_id)) != scalar_bits(scales.at(output_id)))
    return fail("MAX_POOL_2D input and output scales must match exactly");
  return true;
}

static bool validate_reshape_wire_semantics(
    const std::vector<uint8_t>& bytes, size_t operation_index, uint32_t parameter_offset,
    uint32_t parameter_bytes, uint32_t input_id, uint32_t output_id,
    const std::unordered_map<uint32_t, std::vector<uint32_t>>& shapes,
    const std::unordered_map<uint32_t, uint8_t>& dtypes,
    const std::unordered_map<uint32_t, uint8_t>& layouts,
    const std::unordered_map<uint32_t, float>& scales, std::string& error) {
  const std::string prefix = "op " + std::to_string(operation_index) + ": ";
  auto fail = [&](const std::string& message) {
    error = prefix + message;
    return false;
  };
  if (parameter_bytes != TINY3TPU_RESHAPE_PARAMETER_BYTES ||
      parameter_offset > bytes.size() || parameter_bytes > bytes.size() - parameter_offset)
    return fail("RESHAPE parameter record is truncated");
  const uint32_t rank = read_u32(bytes, parameter_offset);
  if (read_u32(bytes, parameter_offset + 20) != 0)
    return fail("nonzero RESHAPE parameter reserved field");
  if (rank == 0 || rank > TINY3TPU_MAX_RANK)
    return fail("invalid RESHAPE rank");

  std::vector<uint32_t> reshaped;
  uint64_t element_count = 1;
  for (uint32_t dimension_index = 0; dimension_index < TINY3TPU_MAX_RANK; ++dimension_index) {
    const uint32_t dimension = read_u32(bytes, parameter_offset + 4 + dimension_index * 4);
    if (dimension_index < rank) {
      if (dimension == 0) return fail("RESHAPE dimensions must be nonzero");
      element_count *= dimension;
      if (element_count > UINT32_MAX) return fail("RESHAPE element count overflows uint32");
      reshaped.push_back(dimension);
    } else if (dimension != 0) {
      return fail("RESHAPE has nonzero unused dimension");
    }
  }
  const auto source_shape = shapes.find(input_id);
  const auto destination_shape = shapes.find(output_id);
  const auto source_dtype = dtypes.find(input_id);
  const auto destination_dtype = dtypes.find(output_id);
  const auto source_layout = layouts.find(input_id);
  const auto destination_layout = layouts.find(output_id);
  const auto source_scale = scales.find(input_id);
  const auto destination_scale = scales.find(output_id);
  if (source_shape == shapes.end() || destination_shape == shapes.end() ||
      source_dtype == dtypes.end() || destination_dtype == dtypes.end() ||
      source_layout == layouts.end() || destination_layout == layouts.end() ||
      source_scale == scales.end() || destination_scale == scales.end())
    return fail("RESHAPE references missing tensor metadata");

  uint64_t source_elements = 1;
  uint64_t destination_elements = 1;
  for (uint32_t dimension : source_shape->second) source_elements *= dimension;
  for (uint32_t dimension : destination_shape->second) destination_elements *= dimension;
  if (source_elements != destination_elements || source_elements != element_count ||
      destination_shape->second != reshaped || source_dtype->second != destination_dtype->second ||
      source_layout->second != destination_layout->second ||
      !scales_equal(source_scale->second, destination_scale->second))
    return fail("RESHAPE descriptor does not preserve shape, dtype, layout, or quantization");
  return true;
}

static bool validate_argmax_wire_semantics(
    const std::vector<uint8_t>& bytes, size_t operation_index, uint32_t parameter_offset,
    uint32_t parameter_bytes, uint32_t input_id, uint32_t output_id,
    const std::unordered_map<uint32_t, std::vector<uint32_t>>& shapes,
    const std::unordered_map<uint32_t, uint8_t>& dtypes, std::string& error) {
  const std::string prefix = "op " + std::to_string(operation_index) + ": ";
  auto fail = [&](const std::string& message) {
    error = prefix + message;
    return false;
  };
  if (parameter_bytes != TINY3TPU_ARGMAX_PARAMETER_BYTES ||
      parameter_offset > bytes.size() || parameter_bytes > bytes.size() - parameter_offset)
    return fail("ARGMAX parameter record is truncated");
  if (read_u32(bytes, parameter_offset) != 0)
    return fail("only ARGMAX axis 0 is supported");
  if (read_u32(bytes, parameter_offset + 4) != 0)
    return fail("nonzero ARGMAX parameter reserved field");
  const auto source_shape = shapes.find(input_id);
  const auto destination_shape = shapes.find(output_id);
  const auto destination_dtype = dtypes.find(output_id);
  if (source_shape == shapes.end() || destination_shape == shapes.end() ||
      destination_dtype == dtypes.end())
    return fail("ARGMAX references missing tensor metadata");
  if (source_shape->second.size() != 1 || destination_dtype->second != TINY3TPU_DTYPE_I32 ||
      destination_shape->second != std::vector<uint32_t>{1})
    return fail("ARGMAX requires rank-1 input and int32 [1] output");
  return true;
}

static bool validate_model_bytes_impl(const std::vector<uint8_t>& bytes, std::string& error) {
  auto fail=[&](const std::string&message){error=message;return false;};
  if(bytes.size()<TINY3TPU_MODEL_HEADER_BYTES)return fail("model shorter than header");
  if(read_u32(bytes, TINY3TPU_HEADER_MAGIC_OFFSET)!=TINY3TPU_MODEL_MAGIC)return fail("bad model magic");if(read_u32(bytes, TINY3TPU_HEADER_VERSION_OFFSET)!=TINY3TPU_MODEL_VERSION)return fail("unsupported model version");if(read_u32(bytes, TINY3TPU_HEADER_BYTES_OFFSET)!=TINY3TPU_MODEL_HEADER_BYTES)return fail("bad header size");if(read_u32(bytes, TINY3TPU_HEADER_TOTAL_BYTES_OFFSET)!=bytes.size())return fail("total size mismatch");
  const uint32_t nt=read_u32(bytes,TINY3TPU_HEADER_TENSOR_COUNT_OFFSET),no=read_u32(bytes,TINY3TPU_HEADER_OPERATION_COUNT_OFFSET),to=read_u32(bytes,TINY3TPU_HEADER_TENSOR_TABLE_OFFSET),oo=read_u32(bytes,TINY3TPU_HEADER_OPERATION_TABLE_OFFSET),po=read_u32(bytes,TINY3TPU_HEADER_PARAMETER_OFFSET),pb=read_u32(bytes,TINY3TPU_HEADER_PARAMETER_BYTES_OFFSET),co=read_u32(bytes,TINY3TPU_HEADER_CONSTANT_OFFSET),cb=read_u32(bytes,TINY3TPU_HEADER_CONSTANT_BYTES_OFFSET),ao=read_u32(bytes,TINY3TPU_HEADER_ARENA_OFFSET),ab=read_u32(bytes,TINY3TPU_HEADER_ARENA_BYTES_OFFSET),so=read_u32(bytes,TINY3TPU_HEADER_SCRATCH_OFFSET),sb=read_u32(bytes,TINY3TPU_HEADER_SCRATCH_BYTES_OFFSET);auto range=[&](uint32_t off,uint32_t len){return off<=bytes.size()&&len<=bytes.size()-off;};auto section_end=[&](uint32_t off,uint32_t len,uint32_t&out){if(!range(off,len))return false;out=off+len;return true;};uint32_t te=0,oe=0,pe=0,ce=0,ae=0;if(nt>UINT32_MAX/TINY3TPU_MODEL_TENSOR_RECORD_BYTES||no>UINT32_MAX/TINY3TPU_MODEL_OPERATION_RECORD_BYTES)return fail("record count overflow");if(!section_end(to,nt*TINY3TPU_MODEL_TENSOR_RECORD_BYTES,te)||!section_end(oo,no*TINY3TPU_MODEL_OPERATION_RECORD_BYTES,oe)||!section_end(po,pb,pe)||!section_end(co,cb,ce)||!section_end(ao,ab,ae))return fail("section bounds overflow");if(to!=TINY3TPU_MODEL_HEADER_BYTES||te!=oo||oe!=po||pe!=co||ce!=ao||ae!=bytes.size())return fail("section ordering or overlap invalid");if(to%4||oo%4||po%4||co%4||ao%16)return fail("section alignment invalid");if(so!=0||sb!=0)return fail("nonzero scratch is unsupported in this ABI");if(read_u32(bytes,TINY3TPU_HEADER_FLAGS_OFFSET)!=0)return fail("nonzero header flags");std::vector<uint8_t> copy=bytes;write_u32(copy,TINY3TPU_HEADER_CRC32_OFFSET,0);if(crc32(copy)!=read_u32(bytes,TINY3TPU_HEADER_CRC32_OFFSET))return fail("CRC mismatch");
  std::unordered_map<uint32_t,uint8_t> tensor_flags; std::unordered_map<uint32_t,uint8_t> layouts; std::unordered_map<uint32_t,std::vector<uint32_t>> shapes; std::unordered_map<uint32_t,uint8_t> dtypes; std::unordered_map<uint32_t,float> scales; std::unordered_map<uint32_t,uint32_t> byte_offsets; std::unordered_map<uint32_t,uint32_t> byte_sizes; std::vector<std::pair<uint32_t,uint32_t>> constant_ranges, arena_ranges; uint32_t input_count=0,output_count=0;
  for(uint32_t i=0;i<nt;++i){
    if (read_u32(bytes, to + size_t(i) * TINY3TPU_MODEL_TENSOR_RECORD_BYTES) == UINT32_MAX)
      return fail("tensor id is reserved for absent operands");
    const size_t p=to+size_t(i)*TINY3TPU_MODEL_TENSOR_RECORD_BYTES; const uint32_t id=read_u32(bytes,p); uint32_t dims[4]={read_u32(bytes,p+8),read_u32(bytes,p+12),read_u32(bytes,p+16),read_u32(bytes,p+20)}; const uint32_t off=read_u32(bytes,p+24),size=read_u32(bytes,p+28),scale_bits_raw=read_u32(bytes,p+32); const uint8_t dtype=bytes[p+4],rank=bytes[p+5],layout=bytes[p+6],flags=bytes[p+7];
    if(tensor_flags.count(id))return fail("duplicate tensor record id"); if(rank==0||rank>4)return fail("invalid tensor rank"); if(layout>2||dtype<1||dtype>3||((flags&~uint8_t(15))!=0))return fail("invalid tensor record fields"); if(read_u32(bytes,p+40)!=0||read_u32(bytes,p+44)!=0)return fail("nonzero tensor reserved field");
    uint64_t count=1; std::vector<uint32_t> shape; for(uint8_t d=0;d<rank;++d){if(dims[d]==0)return fail("zero tensor dimension");count*=dims[d];if(count>UINT32_MAX)return fail("tensor element overflow");shape.push_back(dims[d]);} for(uint8_t d=rank;d<4;++d)if(dims[d]!=0)return fail("nonzero unused tensor dimension"); const uint32_t expected=checked_mul(static_cast<uint32_t>(count),dtype==3?4:1,"tensor byte size");if(size!=expected)return fail("tensor byte size mismatch");const float scale_value=bits_scalar(scale_bits_raw);if(!std::isfinite(scale_value)||scale_value<=0||read_u32(bytes,p+36)!=0)return fail("invalid tensor quantization");
    auto within=[&](uint32_t begin,uint32_t length,uint32_t section_begin,uint32_t section_end){return begin>=section_begin&&begin<=section_end&&length<=section_end-begin;};
    if((flags&TINY3TPU_TENSOR_OUTPUT) && (flags&(TINY3TPU_TENSOR_INPUT|TINY3TPU_TENSOR_CONSTANT|TINY3TPU_TENSOR_SCRATCH)))return fail("output tensor has conflicting flags"); if(flags&TINY3TPU_TENSOR_SCRATCH)return fail("scratch tensors are unsupported in this ABI"); if(off%4!=0||(flags&TINY3TPU_TENSOR_CONSTANT?false:(off%16!=0)))return fail("unaligned tensor storage offset"); if(flags&TINY3TPU_TENSOR_INPUT){++input_count;if(flags&TINY3TPU_TENSOR_CONSTANT)return fail("input constant overlap");if(!within(off,size,ao,ae))return fail("input tensor outside arena");} if(flags&TINY3TPU_TENSOR_CONSTANT){if(!within(off,size,co,ce))return fail("constant tensor offset outside constant section");constant_ranges.emplace_back(off,size);} else {if(!within(off,size,ao,ae))return fail("activation tensor offset outside arena");arena_ranges.emplace_back(off,size);} tensor_flags.emplace(id,flags);layouts.emplace(id,layout);shapes.emplace(id,std::move(shape));dtypes.emplace(id,dtype);scales.emplace(id,scale_value);byte_offsets.emplace(id,off);byte_sizes.emplace(id,size);if(flags&TINY3TPU_TENSOR_OUTPUT)++output_count;
  }
  auto no_overlap=[](std::vector<std::pair<uint32_t,uint32_t>> ranges){std::sort(ranges.begin(),ranges.end());for(size_t i=1;i<ranges.size();++i)if(ranges[i-1].second>ranges[i].first-ranges[i-1].first)return false;return true;};
  if(!no_overlap(constant_ranges)||!no_overlap(arena_ranges))return fail("tensor storage ranges overlap"); if(input_count!=read_u32(bytes,64)||output_count!=read_u32(bytes,68))return fail("tensor flag counts mismatch"); if(output_count==0)return fail("model has no declared outputs");
  std::unordered_set<uint32_t> declared_outputs; for(const auto& entry:tensor_flags)if(entry.second&TINY3TPU_TENSOR_OUTPUT)declared_outputs.insert(entry.first);
  std::unordered_set<uint32_t> available; for(const auto& entry:tensor_flags)if((entry.second&TINY3TPU_TENSOR_INPUT)||(entry.second&TINY3TPU_TENSOR_CONSTANT))available.insert(entry.first); std::unordered_set<uint32_t> produced;
  for(uint32_t i=0;i<no;++i){
    const size_t p=oo+size_t(i)*TINY3TPU_MODEL_OPERATION_RECORD_BYTES;
    const uint32_t opcode=read_u32(bytes,p),version=read_u32(bytes,p+4),param=read_u32(bytes,p+28),size=read_u32(bytes,p+32);
    if(version!=1||read_u32(bytes,p+36)!=0)return fail("invalid operation version/reserved field");
    const uint32_t expected=opcode==TINY3TPU_OP_QGEMM?16:opcode==TINY3TPU_OP_QCONV2D?52:opcode==TINY3TPU_OP_MAX_POOL_2D?36:opcode==TINY3TPU_OP_RESHAPE?24:opcode==TINY3TPU_OP_ARGMAX?8:0;
    if(expected==0||size!=expected||param<po||param>pe||size>pe-param)return fail("invalid operation opcode or parameter range");
    const unsigned input_count_for_op=(opcode==TINY3TPU_OP_QGEMM||opcode==TINY3TPU_OP_QCONV2D)?3:1;
    uint32_t input_ids[3]={UINT32_MAX,UINT32_MAX,UINT32_MAX};
    uint32_t output_id=UINT32_MAX;
    for(unsigned j=0;j<3;++j){const uint32_t id=read_u32(bytes,p+8+j*4);input_ids[j]=id;if(j>=input_count_for_op){if(id!=UINT32_MAX)return fail("unused operation input is not sentinel");}else if(!tensor_flags.count(id)||!available.count(id))return fail("operation input reference/order invalid");}
    for(unsigned j=0;j<2;++j){const uint32_t id=read_u32(bytes,p+20+j*4);if(j>=1){if(id!=UINT32_MAX)return fail("unused operation output is not sentinel");}else{output_id=id;if(!tensor_flags.count(id)||produced.count(id)||(tensor_flags[id]&(TINY3TPU_TENSOR_INPUT|TINY3TPU_TENSOR_CONSTANT)))return fail("operation output reference invalid");}}
    if(opcode==TINY3TPU_OP_QGEMM && !validate_qgemm_wire_semantics(bytes,i,param,size,input_ids[0],input_ids[1],input_ids[2],output_id,tensor_flags,layouts,shapes,dtypes,scales,byte_offsets,byte_sizes,error)) return false;
    if (opcode == TINY3TPU_OP_QCONV2D &&
        !validate_qconv2d_wire_semantics(
            bytes, i, param, size, input_ids[0], input_ids[1], input_ids[2],
            output_id, tensor_flags, layouts, shapes, dtypes, scales,
            byte_offsets, byte_sizes, error))
      return false;
    if (opcode == TINY3TPU_OP_MAX_POOL_2D &&
        !validate_max_pool2d_wire_semantics(
            bytes, i, param, size, input_ids[0], output_id, tensor_flags,
            layouts, shapes, dtypes, scales, error))
      return false;
    if(opcode==TINY3TPU_OP_RESHAPE && !validate_reshape_wire_semantics(bytes,i,param,size,input_ids[0],output_id,shapes,dtypes,layouts,scales,error)) return false;
    if(opcode==TINY3TPU_OP_ARGMAX && !validate_argmax_wire_semantics(bytes,i,param,size,input_ids[0],output_id,shapes,dtypes,error)) return false;
    produced.insert(output_id);available.insert(output_id);
  }
  for (uint32_t id : declared_outputs)
    if (!produced.count(id)) return fail("declared output was never produced: " + std::to_string(id));
  return true;
}

bool validate_model_bytes(const std::vector<uint8_t>& bytes, std::string& error) {
  try { return validate_model_bytes_impl(bytes, error); }
  catch (const std::exception& exception) { error = std::string("validator exception: ") + exception.what(); return false; }
  catch (...) { error = "validator exception"; return false; }
}

Graph import_json_graph(const std::string& path) { return import_graph_value(read_json(path)); }
CompiledModel compile_json_file(const std::string& path) { return compile_graph(import_json_graph(path)); }

namespace {

void require_valid_reference_graph(const Graph& graph) {
  const std::vector<std::string> errors = validate(graph);
  if (errors.empty()) return;
  std::string message = "reference executor: invalid graph:";
  for (const std::string& error : errors) message += "\n - " + error;
  throw std::runtime_error(message);
}

int64_t checked_add_i64(int64_t lhs, int64_t rhs, const char* what) {
  if ((rhs > 0 && lhs > std::numeric_limits<int64_t>::max() - rhs) ||
      (rhs < 0 && lhs < std::numeric_limits<int64_t>::min() - rhs))
    throw std::runtime_error(std::string("reference executor: ") + what + " overflow");
  return lhs + rhs;
}

int64_t checked_mul_i64(int64_t lhs, int64_t rhs, const char* what) {
  if (lhs == 0 || rhs == 0) return 0;
  if ((lhs == -1 && rhs == std::numeric_limits<int64_t>::min()) ||
      (rhs == -1 && lhs == std::numeric_limits<int64_t>::min()) ||
      (lhs > 0 && rhs > 0 && lhs > std::numeric_limits<int64_t>::max() / rhs) ||
      (lhs > 0 && rhs < 0 && rhs < std::numeric_limits<int64_t>::min() / lhs) ||
      (lhs < 0 && rhs > 0 && lhs < std::numeric_limits<int64_t>::min() / rhs) ||
      (lhs < 0 && rhs < 0 && lhs < std::numeric_limits<int64_t>::max() / rhs))
    throw std::runtime_error(std::string("reference executor: ") + what + " overflow");
  return lhs * rhs;
}

int64_t round_shift_symmetric(int64_t value, uint32_t shift) {
  if (shift == 0) return value;
  if (shift > 62) throw std::runtime_error("reference executor: invalid shift");
  const uint64_t magnitude = value < 0
                                 ? static_cast<uint64_t>(-(value + 1)) + 1
                                 : static_cast<uint64_t>(value);
  const uint64_t rounding = uint64_t{1} << (shift - 1);
  if (magnitude > UINT64_MAX - rounding)
    throw std::runtime_error("reference executor: rounding overflow");
  const uint64_t rounded = (magnitude + rounding) >> shift;
  if (rounded > static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
    throw std::runtime_error("reference executor: rounded value overflow");
  const int64_t result = static_cast<int64_t>(rounded);
  return value < 0 ? -result : result;
}

size_t nhwc_index(uint32_t batch, uint32_t height, uint32_t width,
                  uint32_t channels, uint32_t input_height,
                  uint32_t input_width, uint32_t input_channels) {
  return ((static_cast<size_t>(batch) * input_height + height) * input_width +
          width) * input_channels + channels;
}

size_t hwio_index(uint32_t kernel_y, uint32_t kernel_x, uint32_t input_channel,
                  uint32_t output_channel, uint32_t kernel_width,
                  uint32_t input_channels, uint32_t output_channels) {
  return ((static_cast<size_t>(kernel_y) * kernel_width + kernel_x) *
          input_channels + input_channel) * output_channels + output_channel;
}

} // namespace

ReferenceExecutor::ReferenceExecutor(const Graph& graph) : graph_(graph) {
  require_valid_reference_graph(graph_);
  for (const Tensor& tensor : graph_.tensors)
    if (tensor.flags & TINY3TPU_TENSOR_CONSTANT)
      values_.emplace(tensor.id, tensor.data);
}

void ReferenceExecutor::set_input(uint32_t tensor_id,
                                  const std::vector<int32_t>& values) {
  require_valid_reference_graph(graph_);
  const Tensor& tensor = find_tensor(graph_, tensor_id);
  if (!(tensor.flags & TINY3TPU_TENSOR_INPUT))
    throw std::runtime_error("set_input: tensor is not an input");
  if (values.size() != element_count(tensor.shape))
    throw std::runtime_error("set_input: input length mismatch");
  for (int32_t value : values) {
    if ((tensor.dtype == DType::I8 && (value < -128 || value > 127)) ||
        (tensor.dtype == DType::U8 && (value < 0 || value > 255)))
      throw std::runtime_error("set_input: value outside dtype range");
  }
  values_[tensor_id] = values;
}

std::vector<int32_t> ReferenceExecutor::run(uint32_t output_id) {
  require_valid_reference_graph(graph_);
  const Tensor& requested_output = find_tensor(graph_, output_id);
  if (!(requested_output.flags & TINY3TPU_TENSOR_OUTPUT))
    throw std::runtime_error("run: tensor is not an output");
  for (const Operation& operation : graph_.operations) {
    for (uint32_t id : operation.inputs) {
      const auto value = values_.find(id);
      if (value == values_.end())
        throw std::runtime_error("reference executor: missing input tensor");
      if (value->second.size() != element_count(find_tensor(graph_, id).shape))
        throw std::runtime_error("reference executor: tensor value size mismatch");
    }
    if (operation.opcode == Opcode::QCONV2D) {
      const Tensor& a_spec = find_tensor(graph_, operation.inputs[0]);
      const auto& a = values_.at(operation.inputs[0]);
      const auto& w = values_.at(operation.inputs[1]);
      const auto& bias = values_.at(operation.inputs[2]);
      const Tensor& out_spec = find_tensor(graph_, operation.outputs[0]);
      const QConv2DParams p = std::get<QConv2DParams>(operation.params);
      const uint32_t batch = a_spec.shape[0];
      const uint32_t input_height = a_spec.shape[1];
      const uint32_t input_width = a_spec.shape[2];
      const uint32_t input_channels = a_spec.shape[3];
      const uint32_t output_height = out_spec.shape[1];
      const uint32_t output_width = out_spec.shape[2];
      const uint32_t output_channels = out_spec.shape[3];
      std::vector<int32_t> result(element_count(out_spec.shape));
      for (uint32_t batch_index = 0; batch_index < batch; ++batch_index)
        for (uint32_t y = 0; y < output_height; ++y)
          for (uint32_t x = 0; x < output_width; ++x)
            for (uint32_t output_channel = 0; output_channel < output_channels;
                 ++output_channel) {
              int64_t sum = bias[output_channel];
              for (uint32_t kernel_y = 0; kernel_y < p.kernel_h; ++kernel_y)
                for (uint32_t kernel_x = 0; kernel_x < p.kernel_w; ++kernel_x) {
                  const int64_t source_y = static_cast<int64_t>(y) * p.stride_h +
                                           kernel_y - p.pad_top;
                  const int64_t source_x = static_cast<int64_t>(x) * p.stride_w +
                                           kernel_x - p.pad_left;
                  if (source_y < 0 || source_x < 0 ||
                      source_y >= static_cast<int64_t>(input_height) ||
                      source_x >= static_cast<int64_t>(input_width))
                    continue;
                  for (uint32_t input_channel = 0; input_channel < input_channels;
                       ++input_channel) {
                    const size_t input_index = nhwc_index(
                        batch_index, static_cast<uint32_t>(source_y),
                        static_cast<uint32_t>(source_x), input_channel,
                        input_height, input_width, input_channels);
                    const size_t weight_index = hwio_index(
                        kernel_y, kernel_x, input_channel, output_channel,
                        p.kernel_w, input_channels, output_channels);
                    const int64_t product = checked_mul_i64(
                        a[input_index], w[weight_index], "convolution product");
                    sum = checked_add_i64(sum, product, "convolution accumulator");
                  }
                }
              if (sum < INT32_MIN || sum > INT32_MAX)
                throw std::runtime_error("reference executor: convolution accumulator overflow");
              const size_t output_index = nhwc_index(
                  batch_index, y, x, output_channel, output_height, output_width,
                  output_channels);
              if (p.flags & TINY3TPU_QGEMM_FLAG_REQUANT) {
                const int64_t product = checked_mul_i64(
                    sum, p.multiplier, "convolution requantization product");
                int64_t quantized = round_shift_symmetric(product, p.shift);
                if ((p.flags & TINY3TPU_QGEMM_FLAG_RELU) && quantized < 0)
                  quantized = 0;
                result[output_index] = static_cast<int32_t>(
                    std::clamp<int64_t>(quantized, -128, 127));
              } else {
                result[output_index] = static_cast<int32_t>(sum);
              }
            }
      values_[operation.outputs[0]]=std::move(result);
    } else if (operation.opcode == Opcode::MAX_POOL_2D) {
      const Tensor& a_spec = find_tensor(graph_, operation.inputs[0]);
      const Tensor& out_spec = find_tensor(graph_, operation.outputs[0]);
      const auto& a = values_.at(operation.inputs[0]);
      const MaxPool2DParams p = std::get<MaxPool2DParams>(operation.params);
      const uint32_t batch = out_spec.shape[0];
      const uint32_t input_height = a_spec.shape[1];
      const uint32_t input_width = a_spec.shape[2];
      const uint32_t input_channels = a_spec.shape[3];
      const uint32_t output_height = out_spec.shape[1];
      const uint32_t output_width = out_spec.shape[2];
      std::vector<int32_t> result(element_count(out_spec.shape), -128);
      for (uint32_t batch_index = 0; batch_index < batch; ++batch_index)
        for (uint32_t y = 0; y < output_height; ++y)
          for (uint32_t x = 0; x < output_width; ++x)
            for (uint32_t channel = 0; channel < input_channels; ++channel)
              for (uint32_t kernel_y = 0; kernel_y < p.kernel_h; ++kernel_y)
                for (uint32_t kernel_x = 0; kernel_x < p.kernel_w; ++kernel_x) {
                  const int64_t source_y = static_cast<int64_t>(y) * p.stride_h +
                                           kernel_y - p.pad_top;
                  const int64_t source_x = static_cast<int64_t>(x) * p.stride_w +
                                           kernel_x - p.pad_left;
                  if (source_y < 0 || source_x < 0 ||
                      source_y >= static_cast<int64_t>(input_height) ||
                      source_x >= static_cast<int64_t>(input_width))
                    continue;
                  const size_t output_index = nhwc_index(
                      batch_index, y, x, channel, output_height, output_width,
                      input_channels);
                  const size_t input_index = nhwc_index(
                      batch_index, static_cast<uint32_t>(source_y),
                      static_cast<uint32_t>(source_x), channel, input_height,
                      input_width, input_channels);
                  result[output_index] = std::max(result[output_index], a[input_index]);
                }
      values_[operation.outputs[0]]=std::move(result);
    } else if (operation.opcode == Opcode::QGEMM) {
      const Tensor& a_spec = find_tensor(graph_, operation.inputs[0]);
      const Tensor& w_spec = find_tensor(graph_, operation.inputs[1]);
      const auto& a = values_.at(operation.inputs[0]);
      const auto& w = values_.at(operation.inputs[1]);
      const auto& bias = values_.at(operation.inputs[2]);
      const auto p = std::get<QGemmParams>(operation.params);
      const uint32_t m = a_spec.shape.size() == 1 ? 1 : a_spec.shape[0];
      const uint32_t k = w_spec.shape[1];
      const uint32_t n = w_spec.shape[0];
      std::vector<int32_t> result(static_cast<size_t>(m) * n);
      for (uint32_t row = 0; row < m; ++row) {
        for (uint32_t col = 0; col < n; ++col) {
          int64_t sum = bias[col];
          for (uint32_t q = 0; q < k; ++q) {
            const int64_t product = checked_mul_i64(
                a[static_cast<size_t>(row) * k + q],
                w[static_cast<size_t>(col) * k + q], "QGEMM product");
            sum = checked_add_i64(sum, product, "QGEMM accumulator");
          }
          if (sum < std::numeric_limits<int32_t>::min() || sum > std::numeric_limits<int32_t>::max())
            throw std::runtime_error("reference executor: accumulator overflow");
          if (p.flags & TINY3TPU_QGEMM_FLAG_REQUANT) {
            if (p.shift > 62) throw std::runtime_error("reference executor: invalid shift");
            const int64_t product = checked_mul_i64(
                sum, p.multiplier, "QGEMM requantization product");
            int64_t quantized = round_shift_symmetric(product, p.shift);
            if ((p.flags & TINY3TPU_QGEMM_FLAG_RELU) && quantized < 0) quantized = 0;
            result[static_cast<size_t>(row) * n + col] =
                static_cast<int32_t>(std::clamp<int64_t>(quantized, -128, 127));
          } else {
            if (p.flags & TINY3TPU_QGEMM_FLAG_RELU)
              throw std::runtime_error("reference executor: ReLU on int32 output is unsupported");
            result[static_cast<size_t>(row) * n + col] = static_cast<int32_t>(sum);
          }
        }
      }
      values_[operation.outputs[0]] = std::move(result);
    } else if (operation.opcode == Opcode::RESHAPE) {
      values_[operation.outputs[0]] = values_.at(operation.inputs[0]);
    } else if (operation.opcode == Opcode::ARGMAX) {
      const auto& values = values_.at(operation.inputs[0]);
      if (values.empty()) throw std::runtime_error("reference executor: empty argmax");
      int32_t best = 0;
      for (size_t i = 1; i < values.size(); ++i) if (values[i] > values[best]) best = static_cast<int32_t>(i);
      values_[operation.outputs[0]] = {best};
    } else {
      throw std::runtime_error("reference executor: unknown opcode");
    }
  }
  return values_.at(output_id);
}

} // namespace tiny3tpu
