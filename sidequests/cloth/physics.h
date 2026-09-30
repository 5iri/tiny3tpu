/* Port of upstream jaxsim/dflex particle force kernels to on-board float32. */
#include "cloth_data.h"
typedef struct {float x,y,z;} Vec;
static Vec q[PARTICLES],v[PARTICLES],force[PARTICLES];
static float absf(float x){return x<0?-x:x;}
static float rootf(float x){
    if(x<=0)return 0;
    union {float f;unsigned u;} a={x};a.u=(a.u>>1)+0x1fc00000U;
    float r=a.f;for(int i=0;i<5;i++)r=.5f*(r+x/r);return r;
}
static float acosf_local(float x){
    if(x>1)x=1;
    if(x< -1)x=-1;
    float a=absf(x),r=((-0.0187293f*a+0.0742610f)*a-0.2121144f)*a+1.5707288f;
    r*=rootf(1-a);return x<0?3.141592653589793f-r:r;
}
static Vec add(Vec a,Vec b){return (Vec){a.x+b.x,a.y+b.y,a.z+b.z};}
static Vec sub(Vec a,Vec b){return (Vec){a.x-b.x,a.y-b.y,a.z-b.z};}
static Vec mul(Vec a,float b){return (Vec){a.x*b,a.y*b,a.z*b};}
static float dot(Vec a,Vec b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static Vec cross(Vec a,Vec b){return (Vec){a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
static float norm(Vec a){return rootf(dot(a,a));}
static void accum(int i,Vec a){force[i]=add(force[i],a);}
static void reset_physics(void){
 for(int i=0;i<PARTICLES;i++){
 q[i]=(Vec){initial_q[3*i],initial_q[3*i+1],initial_q[3*i+2]};
 v[i]=(Vec){initial_v[3*i],initial_v[3*i+1],initial_v[3*i+2]};}
}
static void physics_step(void){
 for(int i=0;i<PARTICLES;i++)force[i]=(Vec){0,0,0};
 for(int s=0;s<SPRINGS;s++){
  int i=springs[2*s],j=springs[2*s+1];Vec delta=sub(q[i],q[j]);float l=norm(delta);
  Vec dir=mul(delta,1/(l>1e-10f?l:1));
  Vec f=mul(dir,spring_k[s]*(l-spring_length[s])+spring_d[s]*dot(dir,sub(v[i],v[j])));
  accum(i,mul(f,-1));accum(j,f);
 }
 for(int t=0;t<TRIANGLES;t++){
  int i=triangles[3*t],j=triangles[3*t+1],k=triangles[3*t+2];
  Vec qp=sub(q[j],q[i]),rp=sub(q[k],q[i]);const float *d=poses+4*t;
  float invra=2*(d[0]*d[3]-d[1]*d[2]),ra=1/(absf(invra)>1e-10f?invra:1);
  float mu=TRI_MU*ra,lambda=TRI_LAMBDA*ra,damp=TRI_DAMP*ra;
  Vec f1=add(mul(qp,d[0]),mul(rp,d[2])),f2=add(mul(qp,d[1]),mul(rp,d[3]));
  Vec fq=mul(add(mul(f1,d[0]),mul(f2,d[1])),mu),fr=mul(add(mul(f1,d[2]),mul(f2,d[3])),mu);
  Vec n=cross(qp,rp);float len=norm(n);Vec nh=mul(n,1/(len>1e-10f?len:1));
  Vec dcq=mul(cross(rp,nh),invra*.5f),dcr=mul(cross(nh,qp),invra*.5f);
  float c=len*.5f*invra-(1+mu/(absf(lambda)>1e-10f?lambda:1))+activations[t];
  float rate=dot(dcq,v[j])+dot(dcr,v[k])-dot(add(dcq,dcr),v[i]);
  float scalar=lambda*c+damp*rate;
  fq=add(fq,mul(dcq,scalar));fr=add(fr,mul(dcr,scalar));
  accum(i,add(fq,fr));accum(j,mul(fq,-1));accum(k,mul(fr,-1));
 }
 for(int e=0;e<EDGES;e++){
  int i=edges[4*e],j=edges[4*e+1],k=edges[4*e+2],l=edges[4*e+3];
  Vec n1=cross(sub(q[k],q[i]),sub(q[l],q[i])),n2=cross(sub(q[l],q[j]),sub(q[k],q[j]));
  float len1=norm(n1),len2=norm(n2),r1=1/(len1>1e-10f?len1:1),r2=1/(len2>1e-10f?len2:1);
  float cosine=dot(n1,n2)*r1*r2;
  n1=mul(n1,r1*r1);n2=mul(n2,r2*r2);
  Vec edge=sub(q[l],q[k]);float el=norm(edge);Vec eh=mul(edge,1/(el>1e-10f?el:1));
  float sign=dot(cross(n2,n1),eh);sign=sign>0?1:sign<0?-1:0;
  Vec d1=mul(n1,el),d2=mul(n2,el);
  Vec d3=add(mul(n1,dot(sub(q[i],q[l]),eh)),mul(n2,dot(sub(q[j],q[l]),eh)));
  Vec d4=add(mul(n1,dot(sub(q[k],q[i]),eh)),mul(n2,dot(sub(q[k],q[j]),eh)));
  float f=-el*(EDGE_K*(acosf_local(cosine)*sign-rest_angle[e])+EDGE_D*(dot(d1,v[i])+dot(d2,v[j])+dot(d3,v[k])+dot(d4,v[l])));
  accum(i,mul(d1,f));accum(j,mul(d2,f));accum(k,mul(d3,f));accum(l,mul(d4,f));
 }
 for(int i=0;i<PARTICLES;i++){
  Vec a=mul(force[i],inv_mass[i]);if(inv_mass[i]>0)a.y-=9.8f;
  v[i]=add(v[i],mul(a,1.f/7680));q[i]=add(q[i],mul(v[i],1.f/7680));
 }
}
