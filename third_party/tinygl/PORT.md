# TinyGL software backend

Source: https://github.com/jserv/tinygl. The exact commit and original file hashes
are recorded in `UPSTREAM.json`; upstream license is in `LICENSE`.

Local changes for the bounded MuJoCo renderer:

- RGB565 enabled, 32-bit color disabled; strict allocation checks enabled.
- Textured lighting and blending disabled. The scene exporter rejects textured
  and transparent geometry; the GL adapter rejects enabling textures.
- Display-list limit reduced to 32, operation blocks to 512 entries. The eight
  MuJoCo built-in primitive lists fit this bound.
- `list.c`: reserve GL display-list name zero as required by OpenGL; impossible
  internal opcodes use the fatal-error handler instead of calling hosted exit.
- `misc.c`: use increasing NDC-to-depth mapping. MuJoCo already reverses Z in
  its projection, and TinyGL's depth comparison is GEQUAL; retaining TinyGL's
  additional reversal would break occlusion.
- `light.c`: correct the Y/Z components of the local-viewer specular direction.

The port supplies a bounded arena allocator and error handlers instead of
`memory.c` and `msghandling.c`. Allocations occur during initialization. Every
frame checks that arena usage remains constant. The native build uses a larger
arena because pointers and display-list union elements are twice as wide there.
