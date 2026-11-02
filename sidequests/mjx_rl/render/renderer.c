#include <stdarg.h>
#include <string.h>
#include <mujoco/mujoco.h>
#include "renderer.h"
#include "port.h"
#include "scene.h"
#ifndef RENDER_HEAP_BYTES
#define RENDER_HEAP_BYTES (512*1024)
#endif
static union {max_align_t align;unsigned char bytes[RENDER_HEAP_BYTES];} heap;
static size_t allocated;
static mjrContext context;
static mjrRect viewport;
extern void mjr_makeContextTiny(const mjModel *,mjrContext *);
void *port_alloc(size_t bytes){
    bytes=(bytes+15)&~(size_t)15;
    if(bytes>sizeof(heap.bytes)-allocated)port_fail("renderer heap exhausted");
    void *p=heap.bytes+allocated;allocated+=bytes;return p;
}
size_t port_heap_used(void){return allocated;}
void *mju_malloc(size_t bytes){return port_alloc(bytes);}
void mju_free(void *p){if(p)port_fail("unexpected per-frame allocation");}
void mju_error(const char *msg,...){port_fail(msg);}
void mju_warning(const char *msg,...){port_fail(msg);}
void mujoco_renderer_init(uint16_t *pixels,int width,int height){
    if(allocated)port_fail("renderer initialized twice");
    port_gl_init(pixels,width,height);
    mjr_makeContextTiny(&render_model,&context);
    viewport=(mjrRect){0,0,width,height};
}
void mujoco_renderer_draw(const float *poses){
    for(int i=0;i<scene.ngeom;i++){
        mjvGeom *g=scene.geoms+i;
        if(g->objtype==mjOBJ_GEOM && g->objid>=0){
            memcpy(g->pos,poses+12*g->objid,3*sizeof(float));
            memcpy(g->mat,poses+12*g->objid+3,9*sizeof(float));
        }
    }
    size_t used=allocated;
    mjr_render(viewport,&scene,&context);
    if(allocated!=used)port_fail("per-frame allocation");
}
size_t mujoco_renderer_heap(void){return allocated;}
void mju_message(const mjLogMessage *msg){(void)msg;port_fail("MuJoCo log message");}
