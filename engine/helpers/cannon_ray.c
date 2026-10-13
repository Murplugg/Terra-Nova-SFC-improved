/* Supplemental upper-cannon mesh intersections. No renderer globals are written. */
typedef unsigned int U;
typedef struct { double x,y,z; } V;
#include "cannon_mesh_v66.h"
static V sub(V a,V b){return (V){a.x-b.x,a.y-b.y,a.z-b.z};}
static V cross(V a,V b){return (V){a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
static double dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static double trig(U a){
 const short *t=(const short *)0x30f860;
 U n=(a&65535)>>8,f=a&255;
 return (t[n]+(((short)(t[n+1]-t[n])*(int)f)>>8))*(1.0/16384.0);
}
static V body(const int *p,const int *q,double s,double co){
 double dx=(double)q[0]-p[0],dy=(double)q[1]-p[1];
 int z=(int)(((long long)q[2]*2730)>>16);
 return (V){dy*co-dx*s,(double)p[2]-z,dx*co+dy*s};
}
static V upper(V p,double s,double co){
 p=sub(p,(V)UPPER_PIVOT);
 double norm=s*s+co*co;
 return (V){p.y,(co*p.x-s*p.z)/norm,(-s*p.x-co*p.z)/norm};
}
static V barrel(V p,int recoil){
 p=sub(p,(V)BARREL_PIVOT);
 const double a=BARREL_A/65536.0,b=BARREL_B/65536.0,n=a*a+b*b;
 return (V){(a*p.x+b*p.y)/n-recoil,(b*p.x-a*p.y)/n,-p.z};
}
static V vertex(int i){return (V){vertices[i][0],vertices[i][1],vertices[i][2]};}
static double intersect(V o,V end,U lo,U hi){
 const int *bounds=part_bounds[lo?1:0];
 if((o.x<bounds[0] && end.x<bounds[0]) || (o.x>bounds[3] && end.x>bounds[3]) ||
    (o.y<bounds[1] && end.y<bounds[1]) || (o.y>bounds[4] && end.y>bounds[4]) ||
    (o.z<bounds[2] && end.z<bounds[2]) || (o.z>bounds[5] && end.z>bounds[5]))return 2.0;
 V d=sub(end,o);double best=2.0;
 for(U i=lo;i<hi;i++){
  V a=vertex(triangles[i][0]),e1=sub(vertex(triangles[i][1]),a),e2=sub(vertex(triangles[i][2]),a);
  V h=cross(d,e2);double det=dot(e1,h);
  if(det>-0.000001 && det<0.000001)continue;
  V q=sub(o,a);double u=dot(q,h)/det;
  if(u<0.0 || u>1.0)continue;
  V k=cross(q,e1);double v=dot(d,k)/det;
  if(v<0.0 || u+v>1.0)continue;
  double t=dot(e2,k)/det;
  if(t>=0.0 && t<=1.0 && t<best)best=t;
 }
 return best;
}
/* cdecl, returns the nearest 16.16 fraction or -1. ray contains start/end XYZ. */
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int cannon_ray(const int *pose,const int *ray,U angle,int recoil){
 U yaw=*(const unsigned short *)((const char *)pose+12);
 double sy=trig(yaw),cy=trig(yaw+16384),sg=trig(angle),cg=trig(angle+16384);
 V a=upper(body(pose,ray,sy,cy),sg,cg),b=upper(body(pose,ray+3,sy,cy),sg,cg);
 double first=intersect(a,b,0,BARREL_START);
 double second=intersect(barrel(a,recoil),barrel(b,recoil),BARREL_START,TRI_COUNT);
 double hit=first<second?first:second;
 return hit<=1.0?(int)(hit*65536.0):-1;
}
