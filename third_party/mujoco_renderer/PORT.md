# MuJoCo renderer source

Subset of https://github.com/google-deepmind/mujoco, tag **3.15.0**, Apache-2.0.
`UPSTREAM.json` records the original SHA-256 of every vendored file. Includes,
classic rendering sources and required engine utilities are retained; the
linker removes unused functions. No MuJoCo shared library runs on the FPGA.

`src/render/classic/render_gl3.c`, including **mjr_render**, is unmodified.
`render_util.c`, primitive mesh generation and camera utilities are upstream C.

Local changes:

- `render_context.c`: appended `mjr_makeContextTiny`. It initializes the
  CPU-backed default framebuffer and invokes upstream `makeBuiltin`. It omits
  window creation, FBOs, fonts, textures, mesh uploads and shadow resources.
  It does not change `mjr_render` or replace primitive tessellation.
- `engine_util_errmem.h`: under `TINY3TPU_RENDERER`, fatal errors call
  `mju_error` directly without constructing formatted log messages. The board
  error handler terminates execution through its error MMIO port.

The GLAD header supplies the real API signatures. A generated dispatch table
binds supported calls to TinyGL and checked adaptation functions. Unsupported
calls terminate; this is not an implementation of full OpenGL 1.5.
