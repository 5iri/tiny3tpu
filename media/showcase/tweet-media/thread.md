1/ One StableHLO compiler, different workloads on a KC705 FPGA: rotating 3D banana, quantized MLP, causal attention, and an honest pretrained-model memory limit. JAX exports offline; runtime computation stays on the board.

Images: gifs/banana.gif, gifs/classifier.gif, system-config.png, gifs/cloth.gif. Actual physical-board results; cloth playback is time-compressed.

2/ The trained inference case: a small MNIST digit classifier, 784 pixels -> 10 logits. 92.78% int8 accuracy on 10,000 held-out images. Actual board compute: about 104 ms/image. The first 20 test examples are shown, including one model error.

Image: gifs/classifier.gif

3/ The middle case: 8-token causal attention with normalization, six TPU matrix products, softmax, projection and residual. Synthetic weights, not a language-model accuracy benchmark. Board compute: 52.57 ms.

4/ Added a multiplier-free hyperbolic CORDIC for exponential. The compiler selects it for StableHLO exponential on the hardware target. Attention falls to 45.92 ms: 14.5% less compute time, with all 64 fixture outputs bit-exact against the native reference.

5/ The banana angle and camera transform also run on board. One TPU matrix product per frame, about 29.57 ms compute. Host code generates pixels. Display rate includes UART, rasterization and inference sampling, so it is a separate metric.

6/ The hard case is pretrained TinyStories-1M. Even int8 token embeddings alone require 3.07 MiB—49× this no-DDR image's entire 64 KiB RAM. This is a memory audit, not text generation. More storage or a verified weight-streaming path comes next.

7/ Cloth remains the demanding physics example. Small timesteps and software floating point matter. Next work: more generic math lowering and a verified larger-memory runtime. The goal is a reusable compiler/backend, not a collection of handwritten demo kernels.
