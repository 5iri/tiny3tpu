#ifndef MJX_RENDER_PORT_H
#define MJX_RENDER_PORT_H
#include <stddef.h>
#include <stdint.h>
_Noreturn void port_fail(const char *message);
void *port_alloc(size_t bytes);
size_t port_heap_used(void);
void port_gl_init(uint16_t *pixels, int width, int height);
#endif
