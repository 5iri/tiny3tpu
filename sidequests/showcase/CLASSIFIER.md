# Trained MNIST digit classifier

A small linear classifier (784 pixels -> 10 logits) trains offline in JAX for
10 epochs on MNIST's 60,000 training images. Seed: 705. Its final float32
accuracy is 92.85% on the separate 10,000 test images; symmetric int8 weight
quantization and nonnegative int8 pixels give 92.78%. This is a simple trained
baseline, not a state-of-the-art classifier. Training is not performed on FPGA.

The quantized function exports through the generic StableHLO compiler: one
int8 TPU matrix product, int32 bias and accumulation, then CPU logit scaling.
Firmware selects the highest logit on board and returns that predicted digit.
The live host imports no JAX and executes no classifier math. It checks all
returned logit words against precomputed native generated-C results.

The animation uses the first 20 test images, without filtering predictions.
Sample 8 is a model error (5 predicted as 6). The full test-set accuracy above
is evaluated offline; the board regression checks these 20 demo images only.

Dataset: https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz
SHA256: 731c5ac602752760c8e48fbffcf8c3b850d9dc2a2aedcf2cc48468fc17b673d1
Official description: https://keras.io/api/datasets/mnist/

Download to `build-classifier/mnist.npz`, then run:

```sh
python sidequests/showcase/train_classifier.py
```

Build with `tools/kc705_open_build.py route --cpu vexriscv-lite --no-ddr
--cordic --lut6`, passing `--firmware-source
sidequests/showcase/classifier_firmware.c`, `--firmware-include build-classifier`
and `--build-dir build-classifier/board`, plus the usual toolchain paths.
Run `classifier_uart_sim.py` for six production CPU/UART/TPU RTL samples.
Export and program only after routed timing passes, then run
`classifier_live.py`. It verifies the first 20 physical requests and saves
`media/showcase/gifs/classifier.gif` and its capture report, then continues the
live viewer at http://127.0.0.1:8766.

The trained weights, quantized parameters, StableHLO, demo inputs and native
expected logits are preserved in `media/showcase/evidence/classifier`. To use
these without retraining, copy them to `build-classifier`, regenerate
`classifier.h` with the compiler using symbol `classifier`, and regenerate
`digits.h` from `samples.npz`'s `inputs` array. The model and resident demo
samples fit together in the current 64 KiB RAM.
