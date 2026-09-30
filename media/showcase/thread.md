1/ I built tiny3tpu: a tiny int8 TPU on an FPGA. It started with matrix multiplication and digit recognition. Then I wanted to go beyond inference: could the same hardware run tensor programs, 3D transforms and physics? Here’s what we built and what actually runs. 🧵

Attach: system-config.png

2/ The current setup is a KC705 FPGA: a 100 MHz VexRiscv CPU, two 4×4 int8 systolic cores, and 64 KiB of on-chip RAM. The CPU handles state, control and scalar math; the TPU handles matrix products. This demo image has no DDR runtime.

3/ The big change is the compiler. JAX exports a function to StableHLO, then our backend generates RISC-V code and TPU calls. It plans buffers and places supported operations. StableHLO is the interface, so JAX can be one frontend rather than the whole system.

4/ JAX runs offline to export the program. During these demos, the board executes the model or physics step. The host sends commands, receives results and draws pixels. The math comes from compiled programs, not a separate handwritten kernel for each demo.

5/ First, the banana. Its angle updates on the CPU and its camera transform runs on the TPU. About 29.6 ms of board compute per frame. The host does projection, lighting and rasterization. The GIF uses actual geometry returned by the board.

Attach: gifs/banana.gif

6/ Then a real trained digit classifier: 784 pixels → 10 logits. Trained offline on 60,000 MNIST images, then quantized to int8. Held-out accuracy: 92.78% on 10,000 images. Board compute: ~104 ms/image. The GIF shows the first 20 test images, including a mistake.

Attach: gifs/classifier.gif

7/ Next, an 8-token causal attention block: normalization, Q/K/V, masking, softmax, projection and residual. Six matrix products run on the TPU; scalar math runs on the CPU. It uses synthetic weights to test execution, not pretrained language-model quality.

8/ Softmax exposed another bottleneck: exponential in software. We added a multiplier-free hyperbolic CORDIC and a generic StableHLO exponential lowering. On the board, attention fell from 52.57 to 45.92 ms—14.5% less compute time. All 64 checked outputs matched.

9/ Cloth is the harder physics case. Compiled floating-point physics runs on VexRiscv; the TPU transforms the geometry. Around 150 ms per tiny physics step in this capture. The GIF is time-compressed: display FPS and simulated time are different measurements.

Attach: gifs/cloth.gif

10/ And the limit: pretrained TinyStories-1M. Int8 token embeddings alone need 3.07 MiB—49× our current RAM, before other weights and working memory. We audited that limit; we are not running text generation. More storage or verified weight streaming is needed.

11/ The result is a working CPU + TPU compiler path across several workloads, with native, RTL and physical-board checks. It supports a subset of StableHLO today. Next: more generic math acceleration and a larger-memory runtime. Code + demos: github.com/5iri/tiny3tpu
