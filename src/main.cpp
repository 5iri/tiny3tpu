#include "tiny3tpu_compiler.hpp"

#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::vector<int32_t> parse_values(const std::string& text) {
  std::vector<int32_t> values;
  std::stringstream stream(text);
  std::string item;
  while (std::getline(stream, item, ',')) {
    size_t consumed = 0;
    const long value = std::stol(item, &consumed, 10);
    if (consumed != item.size()) throw std::runtime_error("invalid --run-input value");
    values.push_back(static_cast<int32_t>(value));
  }
  if (values.empty()) throw std::runtime_error("--run-input must not be empty");
  return values;
}
} // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: tiny3tpu-compile INPUT.json [-o OUTPUT.t3m] [--run-input v1,v2,...]\n";
    return 2;
  }
  std::string output_path = "model.t3m";
  std::string run_input;
  try {
    for (int index = 2; index < argc; ++index) {
      const std::string option = argv[index];
      if ((option == "-o" || option == "--output") && index + 1 < argc) output_path = argv[++index];
      else if (option == "--run-input" && index + 1 < argc) run_input = argv[++index];
      else throw std::runtime_error("unknown or incomplete option: " + option);
    }
    const tiny3tpu::CompiledModel model = tiny3tpu::compile_json_file(argv[1]);
    std::ofstream output(output_path, std::ios::binary);
    output.write(reinterpret_cast<const char*>(model.bytes.data()), static_cast<std::streamsize>(model.bytes.size()));
    if (!output) throw std::runtime_error("cannot write " + output_path);
    std::cout << "compiled " << argv[1] << " -> " << output_path << " (" << model.bytes.size() << " bytes, " << model.graph.operations.size() << " ops)\n";
    if (!run_input.empty()) {
      tiny3tpu::ReferenceExecutor executor(model.graph);
      executor.set_input(model.graph.inputs.front(), parse_values(run_input));
      const auto result = executor.run(model.graph.outputs.front());
      std::cout << "reference output:";
      for (int32_t value : result) std::cout << ' ' << value;
      std::cout << '\n';
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "compile error: " << error.what() << '\n';
    return 1;
  }
}
