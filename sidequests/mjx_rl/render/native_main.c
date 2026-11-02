#include <stdio.h>
#include <stdlib.h>
#include "renderer.h"
#include "port.h"
static uint16_t pixels[480*270];
_Noreturn void port_fail(const char *message){fprintf(stderr,"Renderer failure: %s\n",message);exit(1);}
int main(int argc,char **argv){
    if(argc!=4)return 2;
    int w=atoi(argv[2]),h=atoi(argv[3]);if(w<=0||h<=0||w%4||w>480||h>270)return 2;
    FILE *f=fopen(argv[1],"rb");if(!f)return 3;
    float poses[12];if(fread(poses,sizeof(float),12,f)!=12)return 4;fclose(f);
    mujoco_renderer_init(pixels,w,h);mujoco_renderer_draw(poses);
    fprintf(stderr,"Renderer heap: %zu bytes\n",mujoco_renderer_heap());
    fwrite(pixels,2,(size_t)w*h,stdout);return 0;
}
