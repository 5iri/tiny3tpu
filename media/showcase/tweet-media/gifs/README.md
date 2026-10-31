# Physical-board GIF captures

- `banana.gif`: 105 unique physical-board transform frames, captured over
  7.89 seconds and encoded at 80 ms/frame. On-board angle update and int8 TPU
  camera transform; host projection, lighting and raster pixels only.
- `classifier.gif`: trained, quantized MNIST classifier results for the first
  20 test examples. Predictions and logits come from the board. Presentation
  holds each image for 0.8 seconds; displayed compute times are actual cycles.
  See `classifier-capture.json` for checks and test accuracy. The earlier fixed
  synthetic MLP animation was replaced by this real classifier capture.
- `cloth.gif`: 51 captured physical-board frames, each after a batch of 32
  compiled physics steps. Playback is deliberately time-compressed at
  100 ms/frame. The tiny physical integration timestep is 1/7680 seconds;
  displayed simulation time is separate from wall time and playback time.
  CPU executes compiled float physics; the int8 TPU executes camera transforms.
  See `cloth-capture.json` for every frame's measured timings and simulation time.

These files are renderings of actual board-returned results, with informational
captions added on the host. They are not synthetic animations or board photographs.
The system configuration PNG beside this folder is exported from Excalidraw;
its editable `.excalidraw` source is also included.
