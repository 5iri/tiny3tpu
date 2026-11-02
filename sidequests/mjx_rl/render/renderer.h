#ifndef MJX_RENDERER_H
#define MJX_RENDERER_H
#include <stddef.h>
#include <stdint.h>
void mujoco_renderer_init(uint16_t *pixels,int width,int height);
void mujoco_renderer_draw(const float *poses);
size_t mujoco_renderer_heap(void);
#endif
