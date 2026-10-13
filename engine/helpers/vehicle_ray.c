/* Supplemental intact utility-vehicle mesh hits. Physical movement is untouched. */
typedef unsigned int U; typedef unsigned char B;
typedef struct { double x,y,z; } V;
typedef struct { int lo[3],hi[3]; U nv,nt; const int (*v)[3];const unsigned short (*t)[3]; const B *header; } Mesh;
#include "vehicle_mesh_v69.h"
static V sub(V a,V b){return (V){a.x-b.x,a.y-b.y,a.z-b.z};}
static V cross(V a,V b){return (V){a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
static double dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static double trig(U a){const short *t=(const short *)0x30f860;U n=(a&65535)>>8,f=a&255;return (t[n]+(((short)(t[n+1]-t[n])*(int)f)>>8))*(1.0/16384.0);}
static int i32(const void *a){return *(const int*)a;}
static V vertex(const Mesh*m,U i){return (V){m->v[i][0],m->v[i][1],m->v[i][2]};}
static double intersect(const Mesh*m,V o,V end){
 if((o.x<m->lo[0]&&end.x<m->lo[0])||(o.x>m->hi[0]&&end.x>m->hi[0])||
    (o.y<m->lo[1]&&end.y<m->lo[1])||(o.y>m->hi[1]&&end.y>m->hi[1])||
    (o.z<m->lo[2]&&end.z<m->lo[2])||(o.z>m->hi[2]&&end.z>m->hi[2]))return 2;
 V d=sub(end,o);double best=2;
 for(U i=0;i<m->nt;i++){
  V a=vertex(m,m->t[i][0]),e1=sub(vertex(m,m->t[i][1]),a),e2=sub(vertex(m,m->t[i][2]),a),h=cross(d,e2);
  double det=dot(e1,h);if(det>-0.000001&&det<0.000001)continue;
  V q=sub(o,a);double u=dot(q,h)/det;if(u<0||u>1)continue;
  V k=cross(q,e1);double v=dot(d,k)/det;if(v<0||u+v>1)continue;
  double t=dot(e2,k)/det;if(t>=0&&t<=1&&t<best)best=t;
 }return best;
}
static V local(V q,const B*obj,U pitch,int offset){
 U yaw=*(const unsigned short*)(obj+27);double s=trig(yaw),co=trig(yaw+16384),sp=trig(pitch),cp=trig(pitch+16384);
 double dx=q.x-i32(obj+15),dy=q.y-i32(obj+19),dz=q.z-i32(obj+23)+offset,forward=dx*co+dy*s;
 return (V){dy*co-dx*s,forward*sp-dz*cp,forward*cp+dz*sp};
}
/* Independent entry for renderer-pose and segment geometry tests. */
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int vehicle_mesh_test(U type,const B*obj,const int*ray,U pitch,int offset){
 const Mesh*m=type==3?&mesh3:type==10?&mesh10:type==11?&mesh11:0;if(!m)return -1;
 V a={ray[0],ray[1],ray[2]},b={ray[3],ray[4],ray[5]};double t=intersect(m,local(a,obj,pitch,offset),local(b,obj,pitch,offset));return t<=1?(int)(t*65536):-1;
}
/* Original Watcom routines wrapped by tiny cdecl bridges in native_vehicle_mesh_v69.py. */
typedef int (*Pitch)(const B*,const B*);typedef int (*Offset)(U);
#define PITCH ((Pitch)0x1fcf800)
#define OFFSET ((Offset)0x1fcf840)
/* query = original origin[3], unit direction[3], maximum distance, excluded external body;
 * point/outputs retain the original terrain, static, or mobile hit unless a nearer mesh wins. */
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int vehicle_ray(const int*q,int result,int*point,int*out1,int*out2,B*flag){
 if(q[6]<0x1999)return result;
 V start={q[0]/6.0,q[1]/6.0,q[2]/6.0},direction={q[3]/65536.0,q[4]/65536.0,q[5]/65536.0};
 double norm=dot(direction,direction);if(norm<0.98||norm>1.02)return result;
 V delta={direction.x*q[6]/6.0,direction.y*q[6]/6.0,direction.z*q[6]/6.0},end={start.x+delta.x,start.y+delta.y,start.z+delta.z};
 double best=1.00000001;
 if(result!=-1||*flag){V prior={point[0]/6.0,point[1]/6.0,point[2]/6.0};best=dot(sub(prior,start),delta)/dot(delta,delta);if(best<0)best=0;if(best>1)best=1;}
 int found=-1;
 for(U id=1;id<300;id++){
  const B*obj=(const B*)(0x3c3240+id*37);if(!obj[0]||obj[1]!=2||!obj[34]||obj[34]==q[7])continue;
  const Mesh*m=obj[2]==3?&mesh3:obj[2]==10?&mesh10:obj[2]==11?&mesh11:0;if(!m)continue;
  U slot=*(const unsigned short*)(obj+3);if(!slot||slot>=52)continue;
  const B*veh=(const B*)(0x3a19e8+slot*296);if((*(const unsigned short*)veh&32767)!=id||*(const short*)(veh+6)<=0)continue;
  int idx=((const int*)0x44b9e4)[obj[34]];if(idx<0||idx>=96||i32((void*)(0x44e0dd+idx*48))<=i32((void*)0x45d5f0))continue;
  /* Broad rejection uses a conservative 24-m radius in world coordinates,
   * independent of the old physics grid/sphere; only the mesh can claim a hit. */
  V pos={i32(obj+15),i32(obj+19),i32(obj+23)},diff=sub(pos,start);double t=dot(diff,delta)/dot(delta,delta);if(t<0)t=0;if(t>best)t=best;
  V near={start.x+delta.x*t,start.y+delta.y*t,start.z+delta.z*t};V gap=sub(near,pos);
  if(dot(gap,gap)>262144.0*262144.0)continue;
  U pitch=PITCH(obj,m->header);int off=OFFSET(id);
  double hit=intersect(m,local(start,obj,pitch,off),local(end,obj,pitch,off));
  if(hit<best){best=hit;found=obj[34];}
 }
 if(found<0)return result;
 point[0]=(int)(q[0]+direction.x*q[6]*best);point[1]=(int)(q[1]+direction.y*q[6]*best);point[2]=(int)(q[2]+direction.z*q[6]*best);
 *out1=0;*out2=0;*flag=1;return found;
}
