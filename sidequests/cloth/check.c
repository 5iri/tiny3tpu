#include <stdio.h>
#include <stdlib.h>
#include "physics.h"
int main(int argc,char **argv){reset_physics();int steps=argc>1?atoi(argv[1]):1920;
for(int i=0;i<steps;i++)physics_step();fwrite(q,sizeof(q),1,stdout);}
