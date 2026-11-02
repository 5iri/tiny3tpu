/* Deliberately bounded software GL backend for MuJoCo's classic renderer. */
#include <math.h>
#include "zgl.h"
#include "port.h"
#define GL_MULTISAMPLE 0x809d
#define GL_FRAMEBUFFER 0x8d40
static int frame_width,frame_height;
static int scissor_full=1;
void port_gl_init(uint16_t *pixels,int width,int height) {
    frame_width=width;frame_height=height;
    ZBuffer *zb=ZB_open(width,height,ZB_MODE_5R6G5B,pixels);
    if(!zb)port_fail("ZB_open");
    glInit(zb);
}
void port_glEnable(unsigned cap) {
    if(cap==GL_MULTISAMPLE)return; /* single-sample framebuffer */
    if(cap==GL_SCISSOR_TEST){if(!scissor_full)port_fail("partial scissor");return;}
    switch(cap){case GL_FOG:case GL_ALPHA_TEST:case GL_STENCIL_TEST:case GL_TEXTURE_2D:
        port_fail("unsupported enabled GL capability");}
    glEnable(cap);
}
void port_glDisable(unsigned cap) {
    switch(cap){case GL_MULTISAMPLE:case GL_SCISSOR_TEST:case GL_FOG:case GL_ALPHA_TEST:
        case GL_STENCIL_TEST:case GL_TEXTURE_GEN_S:case GL_TEXTURE_GEN_T:case GL_TEXTURE_GEN_R:
        case GL_TEXTURE_GEN_Q:case 0x8513:return;}
    glDisable(cap);
}
void port_glDepthFunc(unsigned value){if(value!=GL_GEQUAL)port_fail("depth function");}
void port_glDepthRange(double near,double far){if(near!=0||far!=1)port_fail("depth range");}
void port_glAlphaFunc(unsigned func,float ref){if(func!=GL_GEQUAL||ref!=.99f)port_fail("alpha function");}
void port_glClearStencil(int value){if(value)port_fail("stencil clear");}
void port_glScissor(int x,int y,int w,int h){scissor_full=x==0&&y==0&&w==frame_width&&h==frame_height;}
void port_glLineWidth(float width){if(width!=1)port_fail("line width");}
void port_glFogfv(unsigned name,const float *value){(void)value;if(name!=GL_FOG_COLOR)port_fail("fog parameter");}
void port_glBindFramebuffer(unsigned target,unsigned name){if(target!=GL_FRAMEBUFFER||name)port_fail("framebuffer binding");}
void port_glFinish(void){} /* synchronous software execution */
void port_glOrtho(double l,double r,double b,double t,double n,double f){
    float m[16]={0};m[0]=2/(r-l);m[5]=2/(t-b);m[10]=-2/(f-n);m[12]=-(r+l)/(r-l);m[13]=-(t+b)/(t-b);m[14]=-(f+n)/(f-n);m[15]=1;glMultMatrixf(m);
}
void *gl_malloc(int bytes){return port_alloc((size_t)bytes);}
void *gl_zalloc(int bytes){void *p=port_alloc((size_t)bytes);memset(p,0,(size_t)bytes);return p;}
void gl_free(void *p){(void)p;} /* no per-frame allocations in the accepted scene */
void gl_fatal_error(char *format,...){port_fail(format);}
void tgl_warning(const char *format,...){port_fail(format);}
void tgl_fixme(const char *format,...){port_fail(format);}
void tgl_trace(const char *format,...){(void)format;}

void port_glTexCoord2d(double s,double t){glTexCoord2f((float)s,(float)t);}
